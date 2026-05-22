// Node.js 示例脚本 - JSON 数据格式化工具
// 用法: node json_format.js

const fs = require('fs');
const path = require('path');

console.log('========================================');
console.log('  JSON 数据格式化工具');
console.log('  Node.js 版本:', process.version);
console.log('========================================');
console.log('');

// 示例：格式化一个 JSON 对象
const sampleData = {
    platform: "TEP V1.1",
    version: "1.1.0",
    modules: [
        { name: "执行中心", status: "active" },
        { name: "用例管理", status: "active" },
        { name: "脚本管理", status: "active" },
        { name: "报告看板", status: "active" }
    ],
    supported_scripts: [".py", ".sh", ".bat", ".ps1", ".js", ".rb", ".lua"],
    uptime: process.uptime().toFixed(2) + "s"
};

const formatted = JSON.stringify(sampleData, null, 2);
console.log('格式化输出:');
console.log(formatted);
console.log('');
console.log('系统信息:');
console.log('  平台:', process.platform);
console.log('  架构:', process.arch);
console.log('  内存:', Math.round(process.memoryUsage().heapUsed / 1024 / 1024) + ' MB');
console.log('');
console.log('执行完成！');
