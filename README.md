# TWSE 金融儀表板 + 講義資料庫

## 📊 金融儀表板
- 大盤總覽：加權指數、寶島指數、成交統計
- 個股查詢：輸入股號即時查價
- 本益比/殖利率排行
- 融資融券餘額
- 資料來源：臺灣證券交易所 OpenAPI

## 📚 講義資料庫
- R 金融視覺化講義（18 章）
- Codex 領域學習講義（11 章）
- Codex 五大核心能力（5 章）

## 🔧 本機開啟
直接雙擊 `index.html` 即可瀏覽講義資料庫。
儀表板因瀏覽器 CORS 限制，需透過部署或 proxy 才能正常抓取資料。

## 🚀 部署到 GitHub Pages
1. 在 GitHub 建立 repo（如 `tw-finance-site`）
2. 執行部署指令
3. 開啟 GitHub Pages（Settings → Pages → 選 main branch）
4. 部署 Cloudflare Worker 解決 CORS（見下方）

## 🌤️ Cloudflare Worker CORS Proxy
```js
// 部署到 Cloudflare Workers 即可
export default {
  async fetch(request) {
    const url = new URL(request.url);
    const target = url.searchParams.get('url');
    if (!target) return new Response('Missing ?url=', { status: 400 });
    const resp = await fetch(target);
    const headers = new Headers(resp.headers);
    headers.set('Access-Control-Allow-Origin', '*');
    return new Response(resp.body, { status: resp.status, headers });
  }
}
```
部署後在 `dashboard/index.html` 中將 `PROXY` 改為你的 Worker URL。

## 📄 License
國立臺中科技大學 王美智 © 2026
