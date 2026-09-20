// Swift编译器提供者 · 验证夹具：最小可编译 Swift 源文件。
// 判据不是「能解析」，而是「编译出来能跑并打印中文」——中文能原样输出说明
// 从源码编码、swiftc 编译到进程 stdout 整条链路没有编码损失。
import Foundation

let 名称 = "底座"
let 数字 = 42
print("你好，\(名称)！swiftc 真编译成功，数字=\(数字)")
