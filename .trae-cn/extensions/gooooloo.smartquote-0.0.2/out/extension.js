"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.deactivate = exports.activate = void 0;
const vscode = require("vscode");
function smart_quote_core() {
    const editor = vscode.window.activeTextEditor;
    if (editor) {
        const document = editor.document;
        let selection = editor.selection;
        if (selection.isEmpty) {
            // Idea borrowed from https://github.com/halfcrazy/vscode-pangu/blob/master/src/extension.ts
            selection = new vscode.Selection(new vscode.Position(0, 0), new vscode.Position(Number.MAX_VALUE, Number.MAX_VALUE));
        }
        const word = document.getText(selection);
        var flag = false;
        function foo(_match, _offset, _string) {
            flag = !flag;
            return flag ? "“" : "”";
        }
        ;
        let newtext = word.replace(/["“”]/gi, foo);
        editor.edit(editBuilder => { editBuilder.replace(selection, newtext); });
    }
}
function activate(context) {
    context.subscriptions.push(vscode.commands.registerCommand('smartquote.smart_quote', smart_quote_core));
}
exports.activate = activate;
function deactivate() { }
exports.deactivate = deactivate;
//# sourceMappingURL=extension.js.map