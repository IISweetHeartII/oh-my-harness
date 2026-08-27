<!-- Modified from revfactory/harness (Apache-2.0, Copyright 2025 robin): the
     upstream Japanese README was dropped by PR #56; this rewrites it from the
     v2 content. -->

<p align="center">
  <img src="https://img.shields.io/badge/Version-2.2.0-brightgreen.svg" alt="Version">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License"></a>
  <img src="https://img.shields.io/badge/Claude_Code-Plugin-purple.svg" alt="Claude Code Plugin">
  <img src="https://img.shields.io/badge/実行モード-3種-teal.svg" alt="3 Execution Modes">
  <img src="https://img.shields.io/badge/パターン-6+品質-orange.svg" alt="Patterns">
</p>

# oh-my-harness — Claude Code のためのチームアーキテクチャ工場

[English](README.md) | [한국어](README_KO.md) | **日本語**

> **oh-my-harness は Claude Code 用のチームアーキテクチャ工場です。** 「このプロジェクトのハーネスを構成して」という一文で、プラグインがドメインの説明をエージェントチームと、そのチームが使うスキルへ変換します。

> ### 帰属表示
> `oh-my-harness` は [robin (Minho Hwang)](https://github.com/revfactory) 氏による
> [revfactory/harness](https://github.com/revfactory/harness) の
> **メンテナンス派生版**であり、Apache-2.0 のもとで公開されています。
>
> 上流では優れた v2 の再構築が書かれていますが、2026-07-20 以降マージされないまま
> （マージ競合 + `maintainerCanModify=false`）留まっており、公開されている `main` は
> 削除済み API である `TeamCreate` に依存した v1 のままです。本リポジトリはその v2 の成果に加え、
> レビューのうえ採用したコミュニティのプルリクエストと、ドキュメントの嘘を防ぐ CI を同梱しています。
>
> 完全なクレジットは [NOTICE](./NOTICE) と [docs/ATTRIBUTION.md](./docs/ATTRIBUTION.md) を参照してください。
> `harness` / `evolve` の**スキル名は変更していません** — 慣れ親しんだトリガー文言と
> v1 からの移行経路がそのまま動くようにするためです。

## v2 での変更点

v2 は現行の Claude Code マルチエージェントランタイム向けにゼロから再構築されています。

- **3 つのネイティブ実行モード。** v1 は実験的な `TeamCreate` API を前提とした 2 モードでしたが、その API はすでに存在しません。v2 は現在実際に出荷されているものを対象とします。
  1. **ワークフローオーケストレーション** — 決定的なスクリプト（`pipeline()` / `parallel()` / スキーマ / 予算）によるファンアウト、検証ループ、大規模実行
  2. **永続エージェント協調** — 名前付きエージェント + `SendMessage` + 共有タスクリスト。ターンをまたいでコンテキストを保持
  3. **サブエージェント委譲** — 軽量なワンショット並列ディスパッチ
- **ワークフローネイティブな品質パターン。** 敵対的検証、ジャッジパネル、loop-until-dry、マルチモーダルスイープ、完全性クリティック — 生成されたハーネスが「もっともらしいが誤り」の出力を除去できるよう体系化。
- **実験フラグ不要。** `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` への依存は完全に排除されました。
- **健全なモデルポリシー。** v1 は全エージェントを `model: "opus"` に固定していました。v2 はタスクの複雑さ・所要時間・自律性・レイテンシ要件に応じて opus / sonnet のティアを選択し、根拠のない一括固定を禁止します。
- **`/oh-my-harness:evolve` が実際に出荷されました。** v1 では文書化されているだけだった進化メカニズムが実スキルになりました。初期ハーネスと現行ハーネスの差分を捉え、フィードバックを一般化して、エージェント・スキル・オーケストレーターへ還元します。
- **v1 マイグレーション内蔵。** 工場が v1 の成果物（`TeamCreate`、`TeamDelete`、実験フラグ）を検出し、機械的な移行経路を提示します。

## 主な機能

- **エージェントチーム設計** — 6 つのアーキテクチャパターン（パイプライン、ファンアウト/ファンイン、エキスパートプール、プロデューサー・レビュアー、スーパーバイザー、階層的委譲）。それぞれに最適な v2 実行モードを対応付け
- **スキル生成** — Progressive Disclosure による文脈効率の良いスキル。重複するエージェント・スキルを生成する前に再利用チェック
- **オーケストレーション** — データ受け渡しプロトコル（構造化スキーマ、ファイル、メッセージ、タスク）、エラーハンドリング、再開サポート
- **検証** — トリガー評価、ドライラン、スキルあり／なしの A/B テスト（ワークフローとして実行も可能）
- **進化** — `/oh-my-harness:evolve` が利用フィードバックを測定可能な次世代の改善へ変換

## カテゴリ — このプロジェクトの位置

本プロジェクトは Claude Code エコシステムの **L3 メタファクトリ**層にあります — ハーネス«である»のではなく、ハーネスを«生成する»層です。L3 の中では **チームアーキテクチャ工場**のサブ層を占めます。

| 層 | 役割 | 共存する隣接プロジェクト |
|----|------|------------------------|
| **L3 — メタファクトリ / チームアーキテクチャ工場**（本プロジェクト） | ドメイン一文 → エージェントチーム + スキル。事前定義の 6 パターン経由 | — |
| L3 — メタファクトリ / ランタイム設定工場 | 決定的で再現可能なランタイム設定 | [coleam00/Archon](https://github.com/coleam00/Archon) |
| L3 — メタファクトリ / Codex ランタイムポート | 同じ概念、Codex ランタイム | [SaehwanPark/meta-harness](https://github.com/SaehwanPark/meta-harness) |
| L2 — ハーネス横断ワークフロー | 複数ハーネスにまたがるスキル・ルール・フックの標準化 | [affaan-m/ECC](https://github.com/affaan-m/everything-claude-code) |

> Archon は決定的なランタイム設定を生成します。本プロジェクトはチームアーキテクチャと、エージェントが使うスキルを生成します。ランタイムの決定性が要るなら Archon、チーム設計が要るならこちら、両方を組み合わせることもできます。

## Star History

<a href="https://www.star-history.com/#IISweetHeartII/oh-my-harness&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=IISweetHeartII/oh-my-harness&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=IISweetHeartII/oh-my-harness&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=IISweetHeartII/oh-my-harness&type=Date" />
 </picture>
</a>

## ワークフロー

```
Phase 0: 既存ハーネスの監査（新規 / 拡張 / 保守 — v1 成果物はここで検出）
Phase 1: ドメイン分析（作業の制御フロー形状を含む）
Phase 2: 実行モードとチームアーキテクチャの設計
Phase 3: エージェント定義（.claude/agents/）
Phase 4: スキル生成（.claude/skills/）
Phase 5: オーケストレーションと CLAUDE.md ポインタ
Phase 6: 検証とテスト
Phase 7: 保守 — /oh-my-harness:evolve による進化
```

## インストール

### マーケットプレイス経由

```shell
/plugin marketplace add IISweetHeartII/oh-my-harness
/plugin install oh-my-harness@oh-my-harness-marketplace
```

### グローバルスキルとして

```shell
cp -r skills/harness ~/.claude/skills/harness
cp -r skills/evolve ~/.claude/skills/harness-evolve
```

環境変数も実験フラグも不要です。

## 使い方

```
ハーネスを構成して
하네스 구성해줘
build a harness for this project
design an agent team for <domain>
```

生成したハーネスを使ったあとは:

```
ハーネスを振り返って / evolve the harness with this feedback
```

### 実行モードの選び方

| モード | プリミティブ | 使いどころ |
|--------|-------------|-----------|
| **ワークフローオーケストレーション** | `Workflow` スクリプト | 制御フローが決定的な場合: 列挙可能なファンアウト、検証ループ、大規模実行、構造化出力 |
| **永続エージェント** | `Agent(name:)` + `SendMessage` + タスク | コンテキストを保持する長寿命の専門家。反復的なフィードバックと交渉 |
| **サブエージェント委譲** | ワンショットの `Agent` 呼び出し | 投げっぱなしの並列作業。結果だけが必要な場合 |

工場はチームの人数ではなく、**制御フローの形状**からモードを選びます。フェーズごとにモードを混在させることもあります。

## 生成される成果物

```
your-project/
├── .claude/
│   ├── agents/          # エージェント定義（誰が）
│   │   ├── analyst.md
│   │   ├── builder.md
│   │   └── qa.md
│   └── skills/          # スキル（どうやって）+ オーケストレーター 1 つ（誰が・いつ・どの順で）
│       ├── analyze/SKILL.md
│       └── build/SKILL.md
└── CLAUDE.md            # 最小限のポインタ: トリガールール + 変更履歴
```

## v1 からの移行

[docs/migration-v1-to-v2.md](docs/migration-v1-to-v2.md) を参照してください。要約: `TeamCreate`/`TeamDelete`/ブロードキャスト/フラグへの参照を削除 → ファンアウトを Workflow スクリプトへ変換 → 残る協調を名前付きエージェント + `SendMessage` で書き直し → 一括の `model: "opus"` 固定を解除。工場は v1 成果物を検出すると、この処理を自動化します（Phase 0）。

## 先行研究の結果（v1）

15 件のソフトウェアエンジニアリング課題に対する統制 A/B により、構造化された事前設定が LLM コードエージェントの出力品質に与える影響を測定: 平均品質 49.5 → 79.3（+60%）、勝率 15/15、出力分散 −32%（n=15、著者自身による測定、[revfactory/claude-code-harness](https://github.com/revfactory/claude-code-harness) 参照）。これは著者による測定値です。導入判断にあたっては自分たちでパイロットを実施してください。

## ライセンス

Apache License 2.0 — [LICENSE](./LICENSE) を参照。

本リポジトリは [revfactory/harness](https://github.com/revfactory/harness)（Copyright 2025 robin）の派生著作物です。変更したファイルには変更告知を付し、上流の著作権表示・帰属表示は Apache-2.0 §4 に従ってそのまま保持しています。[NOTICE](./NOTICE) を参照してください。
