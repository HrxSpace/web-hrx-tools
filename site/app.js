/* 检索逻辑：本地数据、无后端。输入即过滤，多关键词按「与」匹配。 */
(() => {
  const DATA = JSON.parse(document.getElementById("shares-data").textContent);
  const byId = new Map(DATA.map((d) => [d.id, d]));
  const input = document.getElementById("q");
  const clearBtn = document.getElementById("clear");
  const statusEl = document.getElementById("status");
  const emptyEl = document.getElementById("empty");
  const suggestEl = document.getElementById("suggest");
  const cards = [...document.querySelectorAll(".card")];
  const chipBox = document.getElementById("chips");
  const dialog = document.getElementById("detail");

  const norm = (s) => (s || "").toLowerCase().replace(/\s+/g, "");
  const haystack = (d) =>
    norm([d.name, d.name_en, d.exe_name, d.category, d.summary, d.description, d.features, d.keywords, d.aliases].flat().join(" "));

  function tokens() {
    return input.value.trim().split(/\s+/).filter(Boolean);
  }

  function mark(el, words) {
    const text = el.dataset.text || el.textContent;
    el.dataset.text = text;
    el.textContent = "";
    if (!words.length) return void el.append(text);
    const re = new RegExp("(" + words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") + ")", "gi");
    let last = 0;
    for (const m of text.matchAll(re)) {
      if (m.index > last) el.append(text.slice(last, m.index));
      const k = document.createElement("mark");
      k.textContent = m[0];
      el.append(k);
      last = m.index + m[0].length;
    }
    el.append(text.slice(last));
  }

  function apply() {
    const words = tokens();
    const active = chipBox.querySelector('.chip[aria-pressed="true"]');
    const cat = active ? active.dataset.cat : "";
    let shown = 0;
    for (const card of cards) {
      const d = byId.get(card.dataset.id);
      if (!d) continue;
      const okCat = !cat || cat === "全部" || d.category === cat;
      const okWord = words.every((w) => haystack(d).includes(norm(w)));
      const visible = okCat && okWord;
      card.hidden = !visible;
      if (visible) {
        shown += 1;
        card.querySelectorAll(".hl").forEach((el) => mark(el, words));
      }
    }
    clearBtn.hidden = !input.value;
    statusEl.textContent = words.length || cat && cat !== "全部"
      ? `匹配 ${shown} / ${cards.length} 款` + (words.length ? `：${words.join(" + ")}` : "")
      : `共 ${cards.length} 款软件`;
    emptyEl.hidden = shown !== 0;
    if (!shown) renderSuggest();
  }

  function renderSuggest() {
    suggestEl.textContent = "";
    const picks = [...new Set(DATA.flatMap((d) => d.keywords || []))]
      .filter((k) => /[一-龥]{2,}/.test(k))
      .slice(0, 6);
    for (const k of picks) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = k;
      b.onclick = () => { input.value = k; apply(); input.focus(); };
      suggestEl.append(b);
    }
  }

  function copy(text, btn) {
    const done = () => {
      const old = btn.textContent;
      btn.textContent = "已复制";
      btn.disabled = true;
      setTimeout(() => { btn.textContent = old; btn.disabled = false; }, 1400);
    };
    if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text).then(done, done);
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.append(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
    done();
  }

  function openDetail(id) {
    const d = byId.get(id);
    if (!d) return;
    const nameEl = document.getElementById("detail-name");
    nameEl.textContent = d.name;
    document.getElementById("detail-sub").textContent =
      [d.name_en, d.exe_name && d.exe_name !== d.name_en ? d.exe_name : "", d.category].filter(Boolean).join(" · ");
    const cover = document.getElementById("detail-cover");
    if (d.cover) {
      cover.src = d.cover;
      cover.alt = `${d.name} 界面截图`;
      cover.hidden = false;
    } else cover.hidden = true;
    document.getElementById("detail-desc").textContent = d.description || d.summary;
    const list = document.getElementById("detail-features");
    list.textContent = "";
    (d.features || []).forEach((f) => list.append(Object.assign(document.createElement("li"), { textContent: f })));
    const meta = document.getElementById("detail-meta");
    meta.textContent = "";
    for (const t of [d.version ? `v${d.version}` : "", d.size_mb ? `${d.size_mb} MB` : "", d.updated ? `更新 ${d.updated}` : ""]) {
      if (t) meta.append(Object.assign(document.createElement("span"), { className: "pill", textContent: t }));
    }
    const cta = document.getElementById("detail-cta");
    cta.textContent = "";
    if (d.status === "coming_soon") {
      cta.append(Object.assign(document.createElement("span"), { className: "pill", textContent: "开发中，即将上架" }));
    }
    cta.append(Object.assign(document.createElement("a"), { className: "btn", href: d.share_url, target: "_blank", rel: "noopener", textContent: `前往下载${d.platform ? "（" + d.platform + "）" : ""}` }));
    const copyBtn = Object.assign(document.createElement("button"), { className: "btn ghost", type: "button", textContent: d.share_code ? `复制提取码 ${d.share_code}` : "复制完整链接" });
    copyBtn.onclick = () => copy(d.share_code ? `${d.share_url}  提取码：${d.share_code}` : d.share_url, copyBtn);
    cta.append(copyBtn);
    dialog.showModal();
  }

  chipBox.addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    chipBox.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", String(c === chip)));
    apply();
  });
  document.getElementById("catalog").addEventListener("click", (e) => {
    const more = e.target.closest("[data-more]");
    if (more) openDetail(more.dataset.more);
  });
  document.getElementById("detail-close").onclick = () => dialog.close();
  dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); });
  input.addEventListener("input", apply);
  clearBtn.onclick = () => { input.value = ""; apply(); input.focus(); };
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && document.activeElement !== input) {
      e.preventDefault();
      input.focus();
      input.select();
    }
    if (e.key === "Escape" && document.activeElement === input && input.value) {
      input.value = "";
      apply();
    }
  });

  apply();
})();
