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
  const sheetBody = dialog.querySelector(".sheet-body");
  const toastEl = document.getElementById("toast");
  const pageToastEl = document.getElementById("page-toast");
  const lightbox = document.getElementById("lightbox");
  const lightboxImg = document.getElementById("lightbox-img");
  const coverBtn = document.getElementById("detail-cover-btn");
  const coverImg = document.getElementById("detail-cover");
  let toastTimer = 0;

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

  function showToast(text) {
    const host = dialog.open ? toastEl : pageToastEl;
    toastEl.classList.remove("show");
    pageToastEl.classList.remove("show");
    host.textContent = text;
    host.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      toastEl.classList.remove("show");
      pageToastEl.classList.remove("show");
    }, 2400);
  }

  function legacyCopy(text) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.cssText = "position:fixed;top:0;left:0;opacity:0;pointer-events:none";
    document.body.append(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch { ok = false; }
    ta.remove();
    return ok;
  }

  function copyText(text) {
    if (navigator.clipboard?.writeText) {
      try {
        return navigator.clipboard.writeText(text).then(() => true, () => legacyCopy(text));
      } catch {
        return Promise.resolve(legacyCopy(text));
      }
    }
    return Promise.resolve(legacyCopy(text));
  }

  function copyCode(code) {
    copyText(code).then((ok) => {
      showToast(ok ? `已复制提取码 ${code}` : `复制失败，请手动选择提取码 ${code}`);
    });
  }

  function linkRow(link, primary, total) {
    const item = document.createElement("div");
    item.className = "dl-item" + (primary ? " primary" : "");
    const main = Object.assign(document.createElement("div"), { className: "dl-main" });
    main.append(Object.assign(document.createElement("span"), {
      className: "dl-platform",
      textContent: link.platform || "网盘链接",
    }));
    if (primary && total > 1) {
      main.append(Object.assign(document.createElement("span"), { className: "dl-tag", textContent: "推荐" }));
    }
    if (link.note) {
      main.append(Object.assign(document.createElement("span"), { className: "dl-note", textContent: link.note }));
    }
    const side = Object.assign(document.createElement("div"), { className: "dl-side" });
    if (link.code) {
      const code = Object.assign(document.createElement("button"), {
        className: "dl-code",
        type: "button",
        title: `点击复制提取码 ${link.code}`,
      });
      code.append("提取码 ");
      code.append(Object.assign(document.createElement("b"), { textContent: link.code }));
      code.addEventListener("click", () => copyCode(link.code));
      side.append(code);
    }
    const open = Object.assign(document.createElement("a"), {
      className: "btn dl-open" + (primary ? "" : " ghost"),
      href: link.url,
      target: "_blank",
      rel: "noopener",
      textContent: link.platform ? `打开${link.platform}` : "打开链接",
    });
    if (link.code) {
      open.addEventListener("click", () => {
        copyText(link.code).then((ok) => {
          showToast(ok
            ? `提取码 ${link.code} 已复制，正在打开${link.platform || "下载页"}`
            : `提取码 ${link.code}，请在新页面手动输入`);
        });
      });
    }
    side.append(open);
    item.append(main, side);
    return item;
  }

  function renderDownloads(d) {
    const box = document.getElementById("detail-links");
    const countEl = document.getElementById("detail-dl-count");
    const tipEl = document.getElementById("detail-dl-tip");
    const links = d.links || [];
    box.textContent = "";
    if (d.status === "coming_soon") {
      countEl.textContent = "";
      box.append(Object.assign(document.createElement("p"), {
        className: "dl-empty",
        textContent: "开发中，即将上架",
      }));
      tipEl.textContent = "上架后会把下载渠道更新到这里。";
      return;
    }
    countEl.textContent = links.length > 1 ? `共 ${links.length} 个` : "";
    links.forEach((link, i) => box.append(linkRow(link, i === 0, links.length)));
    if (!links.length) {
      box.append(Object.assign(document.createElement("p"), {
        className: "dl-empty",
        textContent: "暂未开放下载",
      }));
    }
    tipEl.textContent = links.some((link) => link.code)
      ? "点提取码可以单独复制；打开链接时也会自动复制。下载后解压即用，软件全程在本机运行。"
      : "下载后解压即用；软件全部在你自己的电脑上运行，不需要联网。";
  }

  function openDetail(id) {
    const d = byId.get(id);
    if (!d) return;
    document.getElementById("detail-name").textContent = d.name;
    document.getElementById("detail-sub").textContent =
      [d.name_en, d.exe_name && d.exe_name !== d.name_en ? d.exe_name : "", d.category].filter(Boolean).join(" · ");
    const meta = document.getElementById("detail-meta");
    meta.textContent = "";
    for (const t of [d.version ? `v${d.version}` : "", d.size_mb ? `${d.size_mb} MB` : "", d.updated ? `更新 ${d.updated}` : ""]) {
      if (t) meta.append(Object.assign(document.createElement("span"), { className: "pill", textContent: t }));
    }
    const full = d.cover_full;
    if (full) {
      coverImg.src = full;
      coverImg.alt = `${d.name} 界面截图`;
      coverBtn.hidden = false;
    } else {
      coverImg.removeAttribute("src");
      coverBtn.hidden = true;
    }
    document.getElementById("detail-desc").textContent = d.description || d.summary;
    renderDownloads(d);
    const feats = d.features || [];
    const list = document.getElementById("detail-features");
    list.textContent = "";
    feats.forEach((f) => list.append(Object.assign(document.createElement("li"), { textContent: f })));
    document.getElementById("detail-feats-block").hidden = !feats.length;
    toastEl.classList.remove("show");
    pageToastEl.classList.remove("show");
    dialog.showModal();
    sheetBody.scrollTop = 0;
  }

  function openLightbox() {
    if (!coverImg.getAttribute("src")) return;
    lightboxImg.src = coverImg.src;
    lightboxImg.alt = coverImg.alt;
    lightbox.showModal();
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
  document.addEventListener("click", (e) => {
    const link = e.target.closest("a[data-code]");
    if (!link) return;
    const code = link.dataset.code;
    copyText(code).then((ok) => showToast(ok ? `提取码 ${code} 已复制` : `提取码 ${code}，请手动输入`));
  });
  document.getElementById("detail-close").onclick = () => dialog.close();
  dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); });
  coverBtn.addEventListener("click", openLightbox);
  document.getElementById("lightbox-close").onclick = () => lightbox.close();
  lightbox.addEventListener("click", (e) => { if (e.target === lightbox) lightbox.close(); });
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
