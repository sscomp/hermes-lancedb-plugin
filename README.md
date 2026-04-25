# lancedb-pro-hermes-plugin

Hermes 原生的 LanceDB 長期記憶 plugin。

這個 repo 的定位，是把先前 `openclaw_lancedb` 裡可重用的長期記憶能力，整理成一個正式的 Hermes memory provider plugin，讓 Hermes profile 可以直接安裝與啟用，不再綁定 OpenClaw migration adapter 的語意。

如果你要在新的 Hermes 機器上建立長期長效記憶，這個 repo 就是正式安裝件；它不是 skill，而是 plugin，更精確地說是 memory provider plugin。

## 目前定位

這一版是新的獨立起點：

- plugin 名稱：`hermes_lancedb`
- 類型：Hermes memory provider plugin
- 安裝目標：`<HERMES_HOME>/plugins/hermes_lancedb`

它不是 skill。

## 功能方向

- 以 LanceDB 作為 Hermes 長期記憶存放層
- 提供搜尋、重要記憶摘要、手動寫入
- 支援 profile scope 隔離
- 支援寫入治理規則，避免把閒聊噪音全塞進長期記憶

## 安裝

```bash
git clone https://github.com/sscomp/lancedb-pro-hermes-plugin.git
cd lancedb-pro-hermes-plugin
npm install
scripts/install-profile.sh <profile-name>
```

或明確指定 Hermes profile 路徑：

```bash
scripts/install-profile.sh coder /Users/your-name/.hermes/profiles/coder
```

## 安裝後需要做的事

1. 在 `<PROFILE>/.env` 填入 LanceDB 路徑與 embedding 設定
2. 確認 `<PROFILE>/config.yaml` 內的 `memory.provider` 為 `hermes_lancedb`
3. 重啟 Hermes gateway
4. 驗證 `hermes --profile <profile> memory status`

## 中文快速安裝

如果是在一台新的 Hermes 機器上安裝，建議照這個順序：

1. 先準備好 Hermes profile
2. `git clone` 這個 repo
3. 在 repo 目錄執行 `npm install`
4. 執行：

```bash
scripts/install-profile.sh <profile-name>
```

5. 參考 [examples/profile-env.example](/Users/sscomp/lancedb-pro-hermes-plugin/examples/profile-env.example) 把需要的設定填進 `<PROFILE>/.env`
6. 確認 `<PROFILE>/config.yaml` 內已有：

```yaml
memory:
  provider: hermes_lancedb
```

7. 重啟 Hermes gateway
8. 驗證：

```bash
hermes --profile <profile-name> memory status
```

如果之後要再搭配 NotebookLM 與 Codex dispatch 一起搬機，建議改看可攜式 bootstrap repo 來整體安裝，而不是逐套手動裝。

## Release

- Current release line: `0.1.1`
- Release notes: [docs/release-0.1.1.md](/Users/sscomp/lancedb-pro-hermes-plugin/docs/release-0.1.1.md)

## 重要檔案

- [plugins/hermes_lancedb/plugin.yaml](/Users/sscomp/lancedb-pro-hermes-plugin/plugins/hermes_lancedb/plugin.yaml)
- [plugins/hermes_lancedb/__init__.py](/Users/sscomp/lancedb-pro-hermes-plugin/plugins/hermes_lancedb/__init__.py)
- [plugins/hermes_lancedb/lancedb_bridge.mjs](/Users/sscomp/lancedb-pro-hermes-plugin/plugins/hermes_lancedb/lancedb_bridge.mjs)
- [examples/profile-env.example](/Users/sscomp/lancedb-pro-hermes-plugin/examples/profile-env.example)
- [scripts/install-profile.sh](/Users/sscomp/lancedb-pro-hermes-plugin/scripts/install-profile.sh)

## 與 `openclaw_lancedb` 的關係

建議未來角色分工如下：

- `openclaw_lancedb`：OpenClaw 遷移相容 adapter
- `hermes_lancedb`：Hermes 正式長期記憶 plugin
