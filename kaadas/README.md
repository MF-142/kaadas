# Kaadas Home Assistant 集成

这个目录包含一个基于你提供的 Node-RED Flow 的 Home Assistant 自定义集成骨架，包含：

- 事件轮询：门锁记录
- 门铃记录轮询：访客记录
- 设备信息轮询：电量、WiFi、开锁次数、管理员等
- 用户状态 binary sensor：用户 1~4
- 门铃图片摄像头实体

## 使用方式

1. 将 custom_components/kaadas 目录复制到 Home Assistant 的 custom_components 目录下。
2. 重启 Home Assistant。
3. 进入 设置 -> 设备和服务 -> 添加集成，搜索“凯迪仕门锁”。
4. 填入 token、wifiSN、uid。

## 说明

- Token 是静态值，插件不会主动刷新。
- 当前版本默认按单设备逻辑处理。
- 如果 Token 失效，需要重新配置一次。
