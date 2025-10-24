"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.RulePanel = void 0;
const vscode = __importStar(require("vscode"));
class RulePanel {
    static currentPanel;
    _panel;
    _disposables = [];
    constructor(panel, rules) {
        this._panel = panel;
        this._panel.webview.html = this._getWebviewContent(rules);
        this._panel.onDidDispose(() => this.dispose(), null, this._disposables);
    }
    static show(context, rules) {
        if (RulePanel.currentPanel) {
            RulePanel.currentPanel._panel.reveal(vscode.ViewColumn.One);
            return;
        }
        const panel = vscode.window.createWebviewPanel('cursorRules', 'Cursor Rules 管理', vscode.ViewColumn.One, {
            enableScripts: true
        });
        RulePanel.currentPanel = new RulePanel(panel, rules);
    }
    _getWebviewContent(rules) {
        return `<!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body { 
                    padding: 20px;
                    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
                }
                .rule-card {
                    border: 1px solid #ccc;
                    margin: 10px 0;
                    padding: 15px;
                    border-radius: 5px;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                }
                .rule-info {
                    flex: 1;
                }
                .rule-actions {
                    display: flex;
                    gap: 10px;
                }
                button {
                    padding: 8px 16px;
                    border-radius: 4px;
                    border: none;
                    cursor: pointer;
                }
                .add-btn {
                    background: #007acc;
                    color: white;
                }
                .edit-btn {
                    background: #4CAF50;
                    color: white;
                }
                .delete-btn {
                    background: #f44336;
                    color: white;
                }
            </style>
        </head>
        <body>
            <h2>Cursor Rules 管理</h2>
            <div id="rules-container">
                ${rules.map(rule => `
                    <div class="rule-card">
                        <div class="rule-info">
                            <h3>${rule.name}</h3>
                            <p>${rule.description}</p>
                        </div>
                        <div class="rule-actions">
                            <button class="add-btn" onclick="addRule('${rule.id}')">添加</button>
                            <button class="edit-btn" onclick="editRule('${rule.id}')">编辑</button>
                            ${!rule.isBuiltin ? `<button class="delete-btn" onclick="deleteRule('${rule.id}')">删除</button>` : ''}
                        </div>
                    </div>
                `).join('')}
            </div>
            <script>
                const vscode = acquireVsCodeApi();
                
                function addRule(id) {
                    vscode.postMessage({ command: 'addRule', ruleId: id });
                }
                
                function editRule(id) {
                    vscode.postMessage({ command: 'editRule', ruleId: id });
                }
                
                function deleteRule(id) {
                    vscode.postMessage({ command: 'deleteRule', ruleId: id });
                }
            </script>
        </body>
        </html>`;
    }
    dispose() {
        RulePanel.currentPanel = undefined;
        this._panel.dispose();
        while (this._disposables.length) {
            const disposable = this._disposables.pop();
            if (disposable) {
                disposable.dispose();
            }
        }
    }
}
exports.RulePanel = RulePanel;
//# sourceMappingURL=rulePanel.js.map