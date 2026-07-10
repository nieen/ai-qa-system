# frontend/ai-qa-app/src/components/

## 职责

React 组件层。包含业务组件（ChatInterface / AuthModal）和通用 UI 组件（ui/）。

## 组件

- `ChatInterface.tsx`: 聊天主组件 — 消息列表（Markdown 渲染 + 骨架屏 + 复制）/ 输入区 / 来源面板 / 文档上传状态
- `AuthModal.tsx`: 认证模态框 — 登录/注册切换 / 密码强度校验 / 隐私政策同意 / ESC 关闭
- `ui/button.tsx`: 通用 Button 组件（forwardRef + cn + variants）
- `ui/input.tsx`: 通用 Input 组件（forwardRef + cn）
