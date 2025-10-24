'use strict';
Object.defineProperty(exports, "__esModule", { value: true });
const vscode = require("vscode");
// import Dictionary from './types/Dictionary';
function getPuncpairs() {
    // const editor: any = vscode.window.activeTextEditor;
    const config = getConfig();
    const dictionary = config.get('dictionary', {});
    /* let globalPuncpairs: Object = {};
    let languagePuncpairs: Object = {};
  
    // TODO: move this outside this event
    dictionary.forEach(d => {
      const isGlobal = d.languages.length === 1 && d.languages[0] === '*';
      const isCurrentLanguage = d.languages.includes(editor.document.languageId);
      if (isGlobal) {
        globalPuncpairs = d.puncpairs;
      }
      if (isCurrentLanguage) {
        languagePuncpairs = d.puncpairs;
      }
    });
  
    const puncpairs = Object.assign({}, globalPuncpairs, languagePuncpairs); */
    return dictionary /* [0].puncpairs */;
}
exports.getPuncpairs = getPuncpairs;
function getConfig() {
    // const editor: any = vscode.window.activeTextEditor;
    const config = vscode.workspace.getConfiguration('autopunc'
    // editor.document.uri
    );
    return config;
}
exports.getConfig = getConfig;
//# sourceMappingURL=helpers.js.map