![凯迪仕]([image.png](https://github.com/MF-142/kaadas/blob/main/icon.png))
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
4. 填入`抓包`里的 `token`、`wifiSN`、`uid`、`User-Agent` 和 `phoneName`。

> [推荐使用iphone 抓包](https://apps.apple.com/cn/app/stream/id1312141691)  
> 抓包教程请自行搜索


## 说明

- Token 是静态值，插件不会主动刷新。
- 当前版本默认按单设备逻辑处理。
- 如果 Token 失效，需要重新配置一次。

## 致谢
由hassbian的[@starxxxw](https://bbs.hassbian.com/home.php?mod=space&uid=48929)提供的思路 

原帖在这里：[[流程系列] 凯迪仕门锁通过APP抓包方式接入HA](https://bbs.hassbian.com/thread-24121-1-1.html)
