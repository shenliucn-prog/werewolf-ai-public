# Night Table / 暗夜茶馆 — experimental Android companion

A standalone, offline Android app using this repository's Python rules engine
through Chaquopy and a native Compose interface. No server, model account or
network permission is needed to play. Building requires internet access.

独立离线 Android 应用：同一套 Python 规则引擎、原生 Compose 界面。游玩不需要
服务器、模型账号或联网权限；首次构建需要联网下载依赖。

## Current scope / 当前范围

- Classic free play, random or selected role, and 30 selectable characters.
- Contextual strategy choices, public table/transcript and your private role information.
- Local automatic save, pause/resume, English/Chinese, light/dark themes.
- Android 14+ (API 34), ARM64 only. No iOS build, campaign, model driver,
  portrait gallery or cloud save sync. This is source for an experimental app,
  not a signed store release. Offline choices do not understand free text.

支持经典板自由对局、随机或指定身份、30 人物选择、情境策略选项、公开桌面与本人
私密信息、本地自动存档与续局、中英文及深浅主题。仅支持 Android 14+ ARM64；
未接入闯关、模型、立绘库、云存档，不是已签名的商店发行版，不理解任意文本输入。

## Build / 构建

Install JDK 17+, Android SDK platform 36 and Python 3.12; set `ANDROID_HOME`.
From a Git clone of the repository:

```sh
cd mobile/android
./gradlew :app:assembleDebug :app:lintDebug
# If Python 3.12 isn't on PATH:
./gradlew :app:assembleDebug -Pprobe.python=/absolute/path/to/python3.12
# Optional, with your Android device connected:
./gradlew :app:installDebug
```

安装 JDK 17+、Android SDK 36、Python 3.12，设置 ANDROID_HOME 后执行上述命令。
Gradle 自动从仓库暂存受版本管理的引擎代码、板子和人物文本；不会打包本地设置、
存档或对局日志。修改引擎后重新构建即可。新增引擎文件需先 `git add` 才进入暂存清单。

The debug APK is under `app/build/outputs/apk/debug/`. The application ID stays
`local.werewolf.probe` to preserve existing local installs; upgrading requires
the same signing key. Uninstalling deletes the app's save. Android and desktop
saves are separate and are never uploaded by this app.

APK 位于上述 build 目录。沿用原 application ID 保留本地安装兼容性；覆盖安装要求
同一签名。卸载会删除存档，手机与桌面存档独立，应用不会上传存档。

## Verification / 验证

From the repository root (no model credentials required):

```sh
PYTHONPATH=.:mobile/android/app/src/main/python python -m unittest discover -s mobile/android/tests -q
```

Tests cover player-visible data, stale/duplicate input, pause/resume, a synthetic
complete match and theme contrast. They do not replace device checks for touch,
keyboard, text scaling or accessibility. Source and original vector icons use
the repository's MIT license; system fonts are used and no third-party design
assets are bundled.

测试覆盖信息边界、重复输入、暂停恢复、合成完整对局与主题对比度，不替代真机
触控、键盘、字号和无障碍验收。源码与原创矢量图标沿用仓库 MIT；使用系统字体。
