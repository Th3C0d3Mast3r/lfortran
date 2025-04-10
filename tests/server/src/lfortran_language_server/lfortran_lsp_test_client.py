from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from lsprotocol.types import (
    CompletionClientCapabilities,
    CompletionClientCapabilitiesCompletionItemType,
    CompletionClientCapabilitiesCompletionItemTypeInsertTextModeSupportType,
    CompletionClientCapabilitiesCompletionItemTypeResolveSupportType,
    CompletionClientCapabilitiesCompletionItemTypeTagSupportType,
    CompletionItemTag, DefinitionClientCapabilities, DefinitionParams,
    DocumentHighlightClientCapabilities, HoverClientCapabilities,
    InitializeParams, InsertTextMode, Location, LocationLink, MarkupKind,
    Position, RenameClientCapabilities, RenameParams,
    TextDocumentDefinitionRequest, TextDocumentDefinitionResponse,
    TextDocumentIdentifier, TextDocumentPublishDiagnosticsNotification,
    TextDocumentRenameRequest, TextDocumentRenameResponse, WorkspaceEdit)

from llanguage_test_client.json_rpc import JsonArray, JsonObject
from llanguage_test_client.lsp_test_client import LspTestClient
from llanguage_test_client.lsp_text_document import LspTextDocument


class LFortranLspTestClient(LspTestClient):

    def __init__(
            self,
            server_path: Path,
            server_params: List[str],
            workspace_path: Optional[Path],
            timeout_ms: float,
            config: Dict[str, Any],
            client_log_path: str,
            stdout_log_path: str,
            stdin_log_path: str
    ) -> None:
        super().__init__(
            server_path,
            server_params,
            workspace_path,
            timeout_ms,
            config,
            client_log_path,
            stdout_log_path,
            stdin_log_path
        )

    def await_validation(self, uri: str, version: int) -> Any:
        def is_validation(message: Any) -> bool:
            if message.get("method", None) == "textDocument/publishDiagnostics":
                params = message["params"]
                return params["uri"] == uri \
                    and params.get("version", None) == version
            return False
        event, _ = self.find_incoming_event(lambda event: is_validation(event.data))
        if event is not None:
            return event.data
        while not self.stop.is_set():
            message = self.receive_message()
            if is_validation(message):
                return message
        return None

    def dispatch_method(self, message: JsonObject) -> None:
        match message["method"]:
            case "textDocument/publishDiagnostics":
                notification = self.converter.structure(
                    message,
                    TextDocumentPublishDiagnosticsNotification
                )
                self.receive_text_document_publish_diagnostics(notification)
                self.respond_to_notification()
            case _:
                super().dispatch_method(message)

    def initialize_params(self) -> InitializeParams:
        params = super().initialize_params()
        text_document = params.capabilities.text_document
        if text_document is not None:
            text_document.completion = CompletionClientCapabilities(
                dynamic_registration=True,
                completion_item=CompletionClientCapabilitiesCompletionItemType(
                    snippet_support=False,
                    commit_characters_support=False,
                    documentation_format=[
                        MarkupKind.PlainText,
                        MarkupKind.Markdown,
                    ],
                    deprecated_support=True,
                    preselect_support=False,
                    tag_support=CompletionClientCapabilitiesCompletionItemTypeTagSupportType(
                        value_set=[
                            CompletionItemTag.Deprecated,
                        ],
                    ),
                    insert_replace_support=False,
                    resolve_support=CompletionClientCapabilitiesCompletionItemTypeResolveSupportType(
                        properties=[],
                    ),
                    insert_text_mode_support=CompletionClientCapabilitiesCompletionItemTypeInsertTextModeSupportType(
                        value_set=[
                            InsertTextMode.AsIs,
                            InsertTextMode.AdjustIndentation,
                        ],
                    ),
                    label_details_support=True,
                ),
                context_support=True,
            )
            text_document.hover = HoverClientCapabilities(
                dynamic_registration=True,
                content_format=[
                    MarkupKind.PlainText,
                    MarkupKind.Markdown,
                ],
            )
            text_document.definition = DefinitionClientCapabilities()
            text_document.rename = RenameClientCapabilities()
            text_document.document_highlight = DocumentHighlightClientCapabilities()
        return params

    def receive_text_document_publish_diagnostics(
            self,
            notification: TextDocumentPublishDiagnosticsNotification
    ) -> None:
        pass

    def server_supports_text_document_definition(self) -> bool:
        # NOTE: This returns True if `definition_provider` is True or an instance
        # of `DefinitionOptions`
        return bool(self.server_capabilities.definition_provider)

    def send_text_document_definition(self, params: DefinitionParams) -> int:
        request_id = self.next_request_id()
        request = TextDocumentDefinitionRequest(request_id, params)
        self.send_request(request_id, request,
                          self.receive_text_document_definition)
        return request_id

    def receive_text_document_definition(
            self,
            request: Any,
            message: JsonObject
    ) -> None:
        response = self.converter.structure(
            message,
            TextDocumentDefinitionResponse
        )
        loc: Optional[Union[Location, LocationLink]] = None
        match response.result:
            case Location():
                loc = response.result
            case _ if isinstance(response.result, Sequence) \
                 and not isinstance(response.result, str) \
                 and len(response.result) > 0:
                loc = response.result[0]
        doc: Optional[LspTextDocument] = None
        pos: Optional[Position] = None
        match loc:
            case Location():
                doc = self.documents_by_uri.get(loc.uri, None)
                pos = loc.range.start
            case LocationLink():
                doc = self.documents_by_uri.get(loc.target_uri, None)
                pos = loc.target_range.start
        if doc is not None and pos is not None:
            self.active_document = doc
            doc.cursor = (pos.line + 1, pos.character + 1)

    def goto_definition(self, uri: str, line: int, column: int) -> None:
        if self.server_supports_text_document_definition():
            params = DefinitionParams(
                text_document=TextDocumentIdentifier(
                    uri=uri,
                ),
                position=Position(
                    line=line,
                    character=column
                ),
            )
            request_id = self.send_text_document_definition(params)
            self.await_response(request_id)

    def build_custom_request(
            self,
            method: str,
            request_id: int,
            params: Optional[Union[JsonObject, JsonArray]]
    ) -> JsonObject:
        return {
            "jsonrpc": "2.0",
            "method": method,
            "id": request_id,
            "params": params,
        }

    def send_get_document(self, params: JsonObject) -> int:
        request_id = self.next_request_id()
        request = self.build_custom_request("$/getDocument", request_id, params)
        self.send_request(request_id, request, self.receive_get_document)
        return request_id

    def receive_get_document(
            self,
            request: Any,
            message: JsonObject
    ) -> None:
        pass

    def get_remote_document(self, uri: str) -> JsonObject:
        request_id = self.send_get_document({
            "uri": uri,
        })
        response = self.await_response(request_id)
        return response["result"]

    def server_supports_text_document_rename(self) -> bool:
        return bool(self.server_capabilities.rename_provider)

    def send_text_document_rename(self, params: RenameParams) -> int:
        request_id = self.next_request_id()
        request = TextDocumentRenameRequest(request_id, params)
        self.send_request(request_id, request, self.receive_text_document_rename)
        return request_id

    def apply(self, workspace_edit: WorkspaceEdit) -> None:
        changes = workspace_edit.changes
        if changes is not None:
            for uri, text_edits in changes.items():
                document = self.get_document("fortran", uri)
                document.apply(text_edits)

    def receive_text_document_rename(
            self,
            request: Any,
            message: JsonObject
    ) -> None:
        response = self.converter.structure(
            message,
            TextDocumentRenameResponse
        )
        if response.result is not None:
            self.apply(response.result)

    def rename(self, uri: str, line: int, column: int, new_name: str) -> None:
        if self.server_supports_text_document_rename():
            params = RenameParams(
                text_document=TextDocumentIdentifier(
                    uri=uri,
                ),
                position=Position(
                    line=line,
                    character=column,
                ),
                new_name=new_name,
            )
            request_id = self.send_text_document_rename(params)
            self.await_response(request_id)
