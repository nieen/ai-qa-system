# backend/gateway/internal/service/

## 职责

业务服务层。定义 AuthService / UserService / AdminService 接口及其实现。

## 设计

- `service.go`: 接口定义 + DTO 类型
- `auth_service.go`: 登录（密码校验 + JWT 签发）、注册（密码 hash + 创建用户 + 记录用户同意）
- `user_service.go`: 用户资料、PIPL 合规（数据导出/删除请求/确认/取消）
- `admin_service.go`: 管理员功能（用户列表/角色变更/审计日志/系统统计/数据清理）
