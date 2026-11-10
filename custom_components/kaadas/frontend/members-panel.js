/** Kaadas V1.3.4: standalone, native-HA-style members table; no external libraries. */
class KaadasMembersPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._entries = [];
    this._chosenId = "";
    this._draft = [];
    this._revision = "";
    this._dirty = false;
    this._working = false;
    this._counter = 0;
    this._loaded = false;
  }

  set hass(value) {
    this._hass = value;
    if (this.isConnected && !this._loaded) void this._load();
  }

  set panel(value) { this._panel = value; }
  set narrow(value) { this._narrow = Boolean(value); }
  set route(value) { this._route = value; }

  connectedCallback() {
    this._render();
    if (this._hass && !this._loaded) void this._load();
  }

  async _ws(payload) {
    if (!this._hass) throw new Error("尚未连接Home Assistant");
    return this._hass.connection.sendMessagePromise(payload);
  }

  _message(text, kind = "info") {
    const el = this.shadowRoot.getElementById("message");
    if (!el) return;
    el.textContent = text;
    el.className = `message ${kind}`;
    el.hidden = !text;
  }

  async _load() {
    if (!this._hass || this._working) return;
    this._loaded = true;
    this._working = true;
    this._message("正在读取家庭成员配置……");
    try {
      const result = await this._ws({type: "kaadas/members/get"});
      this._entries = result.entries || [];
      const queryId = new URLSearchParams(window.location.search).get("entry_id");
      const selected = this._entries.find(x => x.entry_id === this._chosenId)
        || this._entries.find(x => x.entry_id === queryId)
        || this._entries[0];
      this._chosenId = selected?.entry_id || "";
      this._useEntry(selected);
      this._render();
      this._message(this._entries.length ? "" : "未找到已配置的凯迪仕门锁。请先添加集成。", this._entries.length ? "info" : "warn");
    } catch (e) {
      this._render();
      this._message(`成员列表读取失败：${this._errorText(e)}`, "error");
    } finally {
      this._working = false;
      this._updateButtons();
    }
  }

  _useEntry(entry) {
    this._draft = (entry?.members || []).map(x => ({
      id: x.id,
      name: String(x.name || ""),
      match_name: String(x.match_name || ""),
      match_mode: x.match_mode === "contains" ? "contains" : "exact",
      feedback: x.feedback !== false,
      notify: Boolean(x.notify),
    }));
    this._revision = entry?.revision || "";
    this._dirty = false;
  }

  _markDirty() {
    this._dirty = true;
    this._updateButtons();
    this._message("有未保存的修改。请点击“保存全部设置”使其生效。", "info");
  }

  _errorText(error) {
    const code = error?.code || "";
    if (code === "conflict") return "其他窗口已更新成员，请刷新列表后重新编辑。";
    if (code === "unauthorized") return "只有HA管理员可以编辑成员。";
    return String(error?.message || error?.error || "请查看HA日志");
  }

  _updateButtons() {
    const save = this.shadowRoot.getElementById("save");
    const add = this.shadowRoot.getElementById("add");
    if (save) save.disabled = this._working || !this._dirty || !this._chosenId;
    if (add) add.disabled = this._working || !this._chosenId;
  }

  _chooseEntry(id) {
    if (this._dirty && !window.confirm("当前有未保存的成员修改，确定放弃并切换门锁吗？")) {
      this._render();
      return;
    }
    const entry = this._entries.find(x => x.entry_id === id);
    if (!entry) return;
    this._chosenId = id;
    this._useEntry(entry);
    const url = new URL(window.location.href);
    url.searchParams.set("entry_id", id);
    window.history.replaceState(window.history.state, "", url);
    this._render();
  }

  _add() {
    this._draft.push({
      id: `tmp:${++this._counter}`, name: "", match_name: "",
      match_mode: "exact", feedback: true, notify: false,
    });
    this._markDirty();
    this._drawRows();
    this.shadowRoot.querySelector("tbody tr:last-child input")?.focus();
  }

  _remove(row) {
    if (!window.confirm(`确定将“${row.name || "未命名成员"}”从待保存列表移除吗？\n此操作只有点击“保存全部设置”后才会生效。`)) return;
    this._draft = this._draft.filter(x => x !== row);
    this._markDirty();
    this._drawRows();
  }

  _cell(row, value, prop, placeholder) {
    const td = document.createElement("td");
    const input = document.createElement("input");
    input.type = "text";
    input.value = value || "";
    input.placeholder = placeholder;
    input.setAttribute("aria-label", placeholder);
    input.maxLength = 100;
    input.addEventListener("input", () => {
      row[prop] = input.value;
      this._markDirty();
    });
    td.appendChild(input);
    return td;
  }

  _checkCell(row, prop, disabled = false) {
    const td = document.createElement("td");
    td.className = "checkcell";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = Boolean(row[prop]);
    input.disabled = disabled;
    input.setAttribute("aria-label", `${row.name || "成员"}：${prop === "feedback" ? "启用开门反馈" : "显示HA通知"}`);
    input.addEventListener("change", () => {
      row[prop] = input.checked;
      if (prop === "feedback" && !input.checked) {
        row.notify = false;
        this._drawRows();
      }
      this._markDirty();
    });
    td.appendChild(input);
    return td;
  }

  _drawRows() {
    const body = this.shadowRoot.querySelector("tbody");
    const empty = this.shadowRoot.getElementById("empty");
    const count = this.shadowRoot.getElementById("count");
    if (!body) return;
    body.replaceChildren();
    if (empty) empty.hidden = this._draft.length > 0;
    if (count) count.textContent = `已配置 ${this._draft.length} 位成员`;
    for (const row of this._draft) {
      const tr = document.createElement("tr");
      tr.appendChild(this._cell(row, row.name, "name", "HA显示名称，如：爸爸"));
      tr.appendChild(this._cell(row, row.match_name, "match_name", "接口昵称"));
      const modeTd = document.createElement("td");
      const sel = document.createElement("select");
      sel.setAttribute("aria-label", `${row.name || "成员"}：匹配方式`);
      for (const [value, label] of [["exact", "精准匹配"], ["contains", "包含匹配"]]) {
        const opt = document.createElement("option");
        opt.value = value;
        opt.textContent = label;
        opt.selected = row.match_mode === value;
        sel.appendChild(opt);
      }
      sel.addEventListener("change", () => {row.match_mode = sel.value; this._markDirty();});
      modeTd.appendChild(sel);
      tr.appendChild(modeTd);
      tr.appendChild(this._checkCell(row, "feedback"));
      tr.appendChild(this._checkCell(row, "notify", !row.feedback));
      const actionTd = document.createElement("td");
      actionTd.className = "checkcell";
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "delete";
      remove.textContent = "删除";
      remove.title = `删除${row.name || "成员"}`;
      remove.addEventListener("click", () => this._remove(row));
      actionTd.appendChild(remove);
      tr.appendChild(actionTd);
      body.appendChild(tr);
    }
    this._updateButtons();
  }

  async _save() {
    if (this._working || !this._dirty) return;
    for (let i = 0; i < this._draft.length; i++) {
      const row = this._draft[i];
      if (!row.name.trim() || !row.match_name.trim()) {
        this._message(`第 ${i + 1} 行未填写完整：必须有HA显示名称和接口昵称。`, "error");
        return;
      }
    }
    this._working = true;
    this._updateButtons();
    this._message("正在保存成员设置……");
    try {
      const response = await this._ws({
        type: "kaadas/members/save", entry_id: this._chosenId,
        revision: this._revision, members: this._draft,
      });
      const index = this._entries.findIndex(x => x.entry_id === this._chosenId);
      if (index >= 0) this._entries[index] = response;
      this._useEntry(response);
      this._drawRows();
      this._message("已保存全部成员设置。Home Assistant 将沿用原有机制重新加载受影响的门锁实体。", "success");
    } catch (error) {
      this._message(`保存失败：${this._errorText(error)}`, "error");
    } finally {
      this._working = false;
      this._updateButtons();
    }
  }

  _render() {
    const root = this.shadowRoot;
    root.innerHTML = `
      <style>
        :host { display:block; height:100%; overflow:auto; color:var(--primary-text-color,#222); background:var(--primary-background-color,#fafafa); font: 15px/1.5 var(--paper-font-body1_-_font-family,Roboto,"Noto Sans SC",sans-serif); box-sizing:border-box; }
        * { box-sizing:border-box; }
        .bar { background:var(--app-header-background-color,var(--card-background-color,#fff)); color:var(--app-header-text-color,var(--primary-text-color)); padding:16px 20px; display:flex; gap:16px; align-items:center; border-bottom:1px solid var(--divider-color,#ddd); }
        h1 { font-size:21px; font-weight:600; margin:0; }
        .container { max-width:1450px; margin:24px auto; padding:0 18px 35px; }
        .card { background:var(--card-background-color,#fff); box-shadow:var(--ha-card-box-shadow,0 1px 4px #0001); border:1px solid var(--divider-color,#ddd); border-radius:14px; padding:18px; }
        .top { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:12px; margin-bottom:16px; }
        .tools { display:flex; align-items:center; flex-wrap:wrap; gap:10px; }
        .back { text-decoration:none; color:var(--primary-color,#03a9f4); font-weight:600; }
        p { margin:8px 0; }
        .hint { color:var(--secondary-text-color,#666); font-size:13px; }
        .table-wrap { width:100%; overflow:auto; border:1px solid var(--divider-color,#ddd); border-radius:9px; }
        table { width:100%; min-width:940px; border-collapse:collapse; text-align:left; }
        thead th { background:var(--secondary-background-color,#f3f3f3); padding:13px 12px; white-space:nowrap; font-weight:600; border-bottom:1px solid var(--divider-color,#ddd); }
        tbody td { padding:8px; border-bottom:1px solid var(--divider-color,#ddd); }
        tbody tr:last-child td { border-bottom:none; }
        tbody tr:hover { background:var(--secondary-background-color,#f5f5f5); }
        td:nth-child(1) { min-width:185px; } td:nth-child(2) { min-width:215px; } td:nth-child(3) { min-width:155px; }
        th:nth-child(4),th:nth-child(5),th:nth-child(6),.checkcell { text-align:center; }
        input[type=text],select { display:block; width:100%; color:var(--primary-text-color,#222); background:var(--card-background-color,#fff); border:1px solid var(--divider-color,#bdbdbd); border-radius:7px; min-height:39px; padding:8px 10px; font:inherit; }
        input[type=checkbox] { width:20px; height:20px; accent-color:var(--primary-color,#03a9f4); cursor:pointer; }
        input:disabled { opacity:.5; cursor:not-allowed; }
        button { cursor:pointer; font:inherit; border:1px solid var(--divider-color,#ddd); color:var(--primary-text-color,#222); background:var(--card-background-color,#fff); border-radius:8px; min-height:38px; padding:8px 15px; }
        button.primary { background:var(--primary-color,#03a9f4); color:#fff; border:0; font-weight:600; }
        button.delete { color:var(--error-color,#b00020); border-color:var(--error-color,#b00020); }
        button:disabled { opacity:.48; cursor:not-allowed; }
        .actions { display:flex; align-items:center; justify-content:flex-end; gap:10px; margin-top:17px; }
        .message { border-radius:8px; margin:0 0 15px; padding:10px 12px; background:var(--secondary-background-color,#eee); }
        .message.error { color:var(--error-color,#b00020); }
        .message.success { color:var(--success-color,#188038); }
        .message.warn { color:var(--warning-color,#a86600); }
        [hidden] { display:none !important; }
        @media (max-width:650px) { .container { margin:14px auto; padding:0 10px 25px; } .card { padding:12px; } h1 { font-size:18px; } .bar { padding:13px; } }
      </style>
      <div class="bar"><a class="back" href="/config/integrations">← 返回集成</a><h1>凯迪仕门锁 · 成员开门反馈管理</h1></div>
      <main class="container"><section class="card">
        <div class="top"><div><strong>家庭成员列表</strong><div class="hint" id="count">已配置 0 位成员</div></div>
          <div class="tools"><label for="entry">选择门锁</label><select id="entry" style="width:auto; min-width:155px"></select>
            <button id="reload">刷新列表</button><button id="add" class="primary">＋ 添加成员</button></div></div>
        <p class="hint">每位成员占一行。接口昵称按门锁记录中显示的原始昵称填写；精准匹配优先，其次最长包含匹配。关闭“开门反馈”会同时关闭该成员通知，但不影响门锁总体状态。</p>
        <div id="message" class="message" role="status" hidden></div>
        <div class="table-wrap" role="region" aria-label="成员横向编辑表格" tabindex="0"><table><thead><tr>
          <th>HA显示名称</th><th>接口昵称</th><th>匹配方式</th><th>开门反馈</th><th>HA通知</th><th>操作</th>
        </tr></thead><tbody></tbody></table></div>
        <p class="hint" id="empty" hidden>还没有成员。点击右上角“添加成员”创建第一位成员。</p>
        <div class="actions"><button id="discard">放弃未保存修改</button><button class="primary" id="save">保存全部设置</button></div>
        <p class="hint">仅修改家庭成员配置；原有API、事件判断、轮询及门铃功能不变。删除成员需确认，且点击保存后才会生效。</p>
      </section></main>`;

    const entrySelector = root.getElementById("entry");
    for (const x of this._entries) {
      const option = document.createElement("option");
      option.value = x.entry_id;
      option.textContent = x.title || "凯迪仕门锁";
      option.selected = x.entry_id === this._chosenId;
      entrySelector.appendChild(option);
    }
    entrySelector.disabled = this._entries.length < 2;
    entrySelector.addEventListener("change", e => this._chooseEntry(e.target.value));
    root.getElementById("add").addEventListener("click", () => this._add());
    root.getElementById("reload").addEventListener("click", () => {
      if (this._dirty && !window.confirm("尚有未保存修改，确认放弃并刷新吗？")) return;
      void this._load();
    });
    root.getElementById("discard").addEventListener("click", () => {
      if (!this._dirty) return;
      if (!window.confirm("确认放弃当前未保存的修改吗？")) return;
      this._useEntry(this._entries.find(x => x.entry_id === this._chosenId));
      this._drawRows();
      this._message("已放弃当前修改。", "info");
    });
    root.getElementById("save").addEventListener("click", () => void this._save());
    this._drawRows();
  }
}

if (!customElements.get("kaadas-members-panel")) {
  customElements.define("kaadas-members-panel", KaadasMembersPanel);
}
