// Package handler — HTTP 处理器层
//
// 本文件已废弃，处理器被拆分为以下文件：
//   new_handler.go   — Handler 结构体 + NewHandler
//   dto.go           — 请求响应 DTO
//   auth_handler.go  — 登录/注册
//   user_handler.go  — 用户资料/PIPL 合规
//   admin_handler.go — 管理功能
//   proxy_handler.go — RAG 代理/健康检查
//
// circuit_breaker.go 和 distributed_breaker.go 已迁移到 internal/proxy/
// 保留在此仅避免 git 删除历史，不会被新代码引用。
package handler
