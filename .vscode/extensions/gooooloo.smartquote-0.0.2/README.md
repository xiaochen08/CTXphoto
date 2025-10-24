# SmartQuote

SmartQuote 插件用于自动修正中文文档里的引号。它假设 `“` 和 `”` 应当依次轮流出现。比如如下这行

> “中文”“中文”“中文”“中文”“中文”“中文”“中文”

应当被修正为

> “中文”“中文”“中文”“中文”“中文”“中文”“中文”



## 功能

![demo](https://github.com/gooooloo/vscode-smartquote/raw/master/images/demo.gif)



## 用法
1. 选中一部分文档内容 -> Command Pallete -> 输入 “Smart Quote”， 然后回车。这个是只修正选中部分。或者
2. 什么都不选，直接 Command Pallete -> 输入 “Smart Quote”， 然后回车。这个是全部修正。



## 已知问题

目前无法处理多个不连续选择的情况。



## 版本信息

### 0.0.1

初始版本



## License

MIT

