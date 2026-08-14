"use strict";

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const SRC_NAMES = {
  robobet: "Robobet",
  robobet_pick: "Robobet·pick",
  sokkerpro: "SokkerPro",
  windrawwin: "Windrawwin",
  bettingexpert: "BettingExpert",
  aiscore: "AiScore",
};

let state = null;
let liveTimer = null;

/* ---------------- helpers ---------------- */

function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) + " · " +
    d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}

function fmtWhen(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const now = Date.now();
  const mins = Math.round((now - d.getTime()) / 60000);
  if (mins < 1) return "agora";
  if (mins < 60) return `há ${mins} min`;
  return fmtTime(iso);
}

function selReliabilityBar(pct) {
  const bar = el("div", "reli-bar");
  const fill = el("i");
  fill.style.width = Math.max(2, Math.min(100, pct * 100)) + "%";
  bar.appendChild(fill);
  return bar;
}

function sourceChips(sources) {
  const chip = (name, st) => {
    const s = el("span", `chip ${st}`);
    s.innerHTML = `<span class="dot"></span>${esc(name)}`;
    return s;
  };
  const frag = document.createDocumentFragment();
  for (const [name, info] of Object.entries(sources)) {
    const st = info.status === "ok" ? "ok" : info.status === "parcial" ? "parcial" : "error";
    frag.appendChild(chip(SRC_NAMES[name] || name, st));
  }
  return frag;
}

const FINISHED_STATUS = new Set(["FT", "AET", "PEN", "FINISHED", "CANCELED", "ABANDONED", "POSTPONED"]);

function sortMatches(matches) {
  const bestRel = (m) => (m.selections && m.selections[0] ? m.selections[0].reliability : 0);
  return matches.slice().sort((a, b) => bestRel(b) - bestRel(a));
}

function isFinished(m) {
  const st = String(m.status || "").toUpperCase();
  if (FINISHED_STATUS.has(st)) return true;
  return false;
}

/* ---------------- renderers ---------------- */

function renderMatchCard(m) {
  const card = el("div", "match-card" + (m.isLive ? " hot" : ""));
  const top = el("div", "mc-top");
  top.appendChild(el("span", "league", esc(m.league || "Futebol")));
  const st = el("span", "statusline");
  if (m.isLive) {
    st.appendChild(el("span", "live-dot"));
    st.appendChild(el("span", "", `ao vivo ${m.live && m.live.minute ? m.live.minute + "'" : ""}`));
  } else if (m.start_time) {
    st.textContent = fmtTime(m.start_time);
  } else if (m.status) {
    st.textContent = esc(m.status);
  } else {
    st.textContent = "hoje";
  }
  top.appendChild(st);
  card.appendChild(top);

  const teams = el("div", "teams");
  const hs = m.scores ? `${esc(m.home)} <span class="score">${esc(m.scores.home)}</span>` : esc(m.home);
  const as = m.scores ? `<span class="score">${esc(m.scores.away)}</span> ${esc(m.away)}` : esc(m.away);
  teams.innerHTML = `<span>${hs}</span><span>${as}</span>`;
  card.appendChild(teams);

  if (m.live && m.live.minute && m.isLive) {
    const min = el("div", "mc-min", `⏱ ${m.live.minute}'`);
    card.appendChild(min);
  }

  const selList = el("div", "sel-list");
  const sels = (m.selections || []).slice(0, 4);
  for (const s of sels) {
    const row = el("div", "sel" + (s.is_pick ? " pick" : ""));
    const name = el("div", "name", `${esc(s.label)} ${s.best_odd ? "" : ""}`);
    if (s.is_pick) name.appendChild(el("span", "badge-pick", "PICK"));
    const odd = el("div", "odd", s.best_odd ? "odd " + Number(s.best_odd).toFixed(2) : "");
    row.appendChild(name);
    row.appendChild(odd);
    const prob = el("div", "prob",
      s.prob_pct != null ? `probabilidade ${s.prob_pct}% · confiabilidade ${Math.round(s.reliability * 100)}%` : "");
    row.appendChild(prob);
    const src = el("div", "sources");
    (s.sources || []).slice(0, 4).forEach((nm) => src.appendChild(el("span", "tag-src", esc(SRC_NAMES[nm] || nm))));
    row.appendChild(src);
    row.appendChild(selReliabilityBar(s.reliability));
    selList.appendChild(row);
  }
  card.appendChild(selList);

  if (m.live && m.live.corners && (m.live.corners.home != null || m.live.corners.away != null)) {
    const n = el("ul", "note-stats");
    n.appendChild(el("li", "", `🔄 Escanteios: ${m.live.corners.home ?? "-"} x ${m.live.corners.away ?? "-"}`));
    if (m.live.shots_on) n.appendChild(el("li", "", `🎯 Chutes no gol: ${m.live.shots_on.home ?? "-"} x ${m.live.shots_on.away ?? "-"}`));
    if (m.live.possession) n.appendChild(el("li", "", `🧲 Posse: ${m.live.possession.home ?? "-"}% x ${m.live.possession.away ?? "-"}%`));
    card.appendChild(n);
  }

  if (m.live && m.live.ww_stats && m.live.ww_stats.length) {
    const n = el("ul", "note-stats");
    m.live.ww_stats.slice(0, 2).forEach((t) => n.appendChild(el("li", "", `📊 ${esc(t)}`)));
    card.appendChild(n);
  }

  return card;
}

function renderToday(data) {
  const box = $("#todayContent");
  box.innerHTML = "";

  const acca = data.accumulator.recommended;
  const panel = el("div", "panel");
  const head = el("div", "panel-head");
  head.appendChild(el("h2", "", "📋 Previsões de hoje — melhores seleções por jogo"));

  const all = data.predictions.matches.filter((m) => !isFinished(m));
  const live = all.filter((m) => m.isLive);
  const upcoming = all.filter((m) => !m.isLive);
  const sub = el("div", "sub",
    `Atualizado ${fmtWhen(data.predictions.generated_at)} · ${all.length} jogos (${live.length} ao vivo, ${upcoming.length} a iniciar) de ${data.predictions.matches.length} agregados`);
  head.appendChild(sub);
  panel.appendChild(head);

  if (acca) {
    const strip = el("div", "acca-strip");
    const p = el("p", "", `🎯 Acumuladora recomendada: ${acca.odd.toFixed(2)} (${acca.legs.length} jogos) — veja a aba Acumuladora`);
    const btn = el("button", "btn btn-mini", "ver detalhes");
    btn.addEventListener("click", () => switchTab("acca"));
    strip.appendChild(p);
    strip.appendChild(btn);
    panel.appendChild(strip);
  }

  const ordered = sortMatches([...live, ...upcoming]);
  const grid = el("div", "match-grid");
  const LIMIT = 60;
  let shown = 0;
  for (const m of ordered) {
    if (shown >= LIMIT) break;
    grid.appendChild(renderMatchCard(m));
    shown++;
  }
  panel.appendChild(grid);
  box.appendChild(panel);

  if (ordered.length > LIMIT) {
    const more = el("button", "btn", `Mostrar mais ${ordered.length - LIMIT} jogos`);
    more.style.marginTop = "12px";
    more.addEventListener("click", () => {
      for (let i = LIMIT; i < ordered.length; i++) grid.appendChild(renderMatchCard(ordered[i]));
      more.remove();
    });
    box.appendChild(more);
  }

  // windrawwin acca
  const ww = data.predictions.windrawwin_acca;
  if (ww && ww.odd) {
    const w = el("div", "ww-acca");
    w.appendChild(el("h3", "", "📌 Acumuladora do Windrawwin (site oficial)"));
    const r1 = el("div", "row");
    r1.appendChild(el("span", "", esc(ww.date || "")));
    r1.appendChild(el("span", "odd", "odd " + Number(ww.odd).toFixed(2)));
    w.appendChild(r1);
    (ww.legs || []).slice(0, 8).forEach((l) => {
      if (l.home) {
        const r = el("div", "row");
        r.appendChild(el("span", "", `${esc(l.home)} x ${esc(l.away)} — ${esc(l.market)}`));
        r.appendChild(el("span", "muted", l.odds ? Number(l.odds).toFixed(2) : esc(l.fraction || "")));
        w.appendChild(r);
      }
    });
    box.appendChild(w);
  }
}

function renderAcca(data) {
  const box = $("#accaContent");
  box.innerHTML = "";
  const acca = data.accumulator;

  const variants = [
    { key: "recommended", label: "Mais confiável" },
    { key: "balanced", label: "Equilibrada" },
    { key: "max_odd_combo", label: "Maior odd (≤ 4.00)" },
  ];

  const pick = (combo) => combo || acca.recommended;
  const active = pick(acca.recommended);
  if (!active) {
    box.appendChild(el("div", "empty", "Nenhuma acumuladora válida no momento (sem jogos com odd entre 1.10 e 4.00)."));
    return;
  }

  // variant switcher
  const switcher = el("div", "acca-strip");
  const swLabel = el("span", "", "Modo da acumuladora:");
  swLabel.style.fontWeight = "700";
  switcher.appendChild(swLabel);
  const swBtns = el("div", "");
  swBtns.style.display = "flex";
  swBtns.style.gap = "8px";
  swBtns.style.flexWrap = "wrap";
  variants.forEach((v) => {
    const combo = acca[v.key];
    const b = el("button", "btn btn-mini", `${v.label} · odd ${combo ? Number(combo.odd).toFixed(2) : "—"}`);
    if (v.key === "recommended" || (v.key !== "recommended" && !combo)) b.style.opacity = "1";
    b.addEventListener("click", () => {
      if (combo) renderAccaCombo(data, combo, acca);
    });
    swBtns.appendChild(b);
  });
  switcher.appendChild(swBtns);
  box.appendChild(switcher);

  renderAccaCombo(data, active, acca);
}

function renderAccaCombo(data, combo, acca) {
  const box = $("#accaContent");
  // remove the previously rendered main area (keep switcher)
  const old = box.querySelector(".acca-wrap, .acca-alt, .acca-how");
  if (old) old.remove();

  const wrap = el("div", "acca-wrap");
  const main = el("div", "acca-card");
  main.appendChild(el("h2", "", "🎯 Acumuladora recomendada do dia"));

  const oddRow = el("div", "acca-odd-row");
  oddRow.appendChild(el("span", "acca-odd", `Odd total ${Number(combo.odd).toFixed(2)}`));
  const rel = el("span", "acca-rel",
    `confiabilidade ${Math.round(combo.reliability * 100)}% · prob. média ${Math.round((combo.avg_prob || 0) * 100)}% · máx. ${acca.max_legs} jogos · odd ≤ ${acca.max_odd}`);
  oddRow.appendChild(rel);
  main.appendChild(oddRow);

  combo.legs.forEach((l, i) => {
    const leg = el("div", "acca-leg");
    const left = el("div", "");
    const selName = el("div", "selname");
    selName.innerHTML = `<span class="num">${i + 1}.</span> ${esc(l.home)} x ${esc(l.away)} — ${esc(l.selection_label)}`;
    left.appendChild(selName);
    left.appendChild(el("div", "meta",
      `${esc(l.league)} · ${fmtTime(l.start_time)} · fontes: ${(l.sources || []).map((s) => esc(SRC_NAMES[s] || s)).join(", ")}`));
    leg.appendChild(left);
    leg.appendChild(el("span", "odd", Number(l.odd).toFixed(2)));
    main.appendChild(leg);
  });
  wrap.appendChild(main);

  const side = el("div", "acca-alt");
  side.appendChild(el("h3", "", "Alternativas (top combos)"));
  const ul = el("ul", "");
  (acca.alternatives || []).forEach((c) => {
    const li = el("li");
    li.appendChild(el("span", "", `${c.legs.length} jogos · conf. ${Math.round(c.reliability * 100)}%`));
    li.appendChild(el("span", "o", `odd ${Number(c.odd).toFixed(2)}`));
    ul.appendChild(li);
  });
  side.appendChild(ul);

  const sb = data.predictions.robobet_scoreboard;
  if (sb && sb.overall) {
    side.appendChild(el("h3", "", "Histórico Robobet (mês atual)"));
    const grid = el("div", "stats-grid");
    const mk = (v, l, cls) => {
      const s = el("div", "stat " + (cls || ""));
      s.appendChild(el("div", "v", v));
      s.appendChild(el("div", "l", l));
      return s;
    };
    grid.appendChild(mk(sb.overall.hit_rate != null ? sb.overall.hit_rate + "%" : "-", "Taxa de acerto", "good"));
    grid.appendChild(mk(sb.overall.roi_pct != null ? sb.overall.roi_pct + "%" : "-", "ROI", sb.overall.roi_pct > 0 ? "good" : "bad"));
    grid.appendChild(mk(sb.overall.avg_odd != null ? Number(sb.overall.avg_odd).toFixed(2) : "-", "Odd média"));
    grid.appendChild(mk(sb.overall.settled != null ? sb.overall.settled : "-", "Dicas liquidadas"));
    side.appendChild(grid);
  }
  wrap.appendChild(side);
  box.appendChild(wrap);

  const how = el("div", "panel");
  const head = el("div", "panel-head");
  head.appendChild(el("h2", "", "Como a acumuladora é construída"));
  const sub = el("div", "sub", "regras: no máximo 3 jogos · odd combinada ≤ 4.00 · maximiza confiabilidade");
  head.appendChild(sub);
  how.appendChild(head);
  const p = el("p", "", "");
  p.innerHTML =
    "Cada jogo contribui com a <b>seleção mais confiável</b> (acordo entre fontes × probabilidade do modelo). " +
    "A confiabilidade combina a probabilidade média dos modelos (Robobet, SokkerPro) com o número de fontes concordando " +
    "e picks oficiais da Robobet. A melhor combinação de 1 a 3 jogos com odd entre 1.05 e 4.00 é escolhida por maior confiabilidade.";
  how.appendChild(p);
  box.appendChild(how);
}

function renderYoutube(data) {
  const box = $("#youtubeContent");
  box.innerHTML = "";
  const yt = data.youtube;

  if (!yt || (!yt.groups || !yt.groups.length)) {
    box.appendChild(el("div", "empty", "Não foi possível buscar vídeos agora. Tente novamente em instantes."));
    return;
  }

  for (const g of yt.groups) {
    const grp = el("div", "yt-group");
    const h = el("h3");
    h.innerHTML = `▶ <a href="${esc(g.search_url)}" target="_blank" rel="noopener">${esc(g.query)}</a>`;
    grp.appendChild(h);
    if (!g.videos.length) {
      grp.appendChild(el("div", "empty", "sem resultados desta busca."));
    } else {
      const grid = el("div", "yt-grid");
      for (const v of g.videos) {
        const a = el("a", "yt-card");
        a.href = v.url;
        a.target = "_blank";
        a.rel = "noopener";
        if (v.thumbnail) {
          const img = el("img", "yt-thumb");
          img.src = v.thumbnail;
          img.loading = "lazy";
          img.alt = "";
          a.appendChild(img);
        }
        const body = el("div", "yt-body");
        body.appendChild(el("div", "yt-title", esc(v.title)));
        const meta = el("div", "yt-meta");
        if (v.channel) meta.appendChild(el("span", "", `🎙 ${esc(v.channel)}`));
        if (v.views) meta.appendChild(el("span", "", `👁 ${esc(v.views)}`));
        if (v.published) meta.appendChild(el("span", "", esc(v.published)));
        if (v.length) meta.appendChild(el("span", "", `⏱ ${esc(v.length)}`));
        body.appendChild(meta);
        a.appendChild(body);
        grid.appendChild(a);
      }
      grp.appendChild(grid);
    }
    box.appendChild(grp);
  }
}

function renderLive(data) {
  const box = $("#liveContent");
  box.innerHTML = "";
  const live = data.live;

  const layout = el("div", "live-layout");

  // signals
  const left = el("div", "panel");
  const head = el("div", "panel-head");
  head.appendChild(el("h2", "", "🔔 Sinais e entradas"));
  head.appendChild(el("div", "sub", `atualizado ${fmtWhen(live.refreshed_at)} · atualização automática a cada 45s`));
  left.appendChild(head);
  const list = el("div", "signal-list");
  if (!live.signals || !live.signals.length) {
    list.appendChild(el("div", "empty", "Sem sinais novos no momento. Os sinais aparecem quando há gol, escanteio, ritmo forte ou entrada da Robobet em jogos ao vivo."));
  } else {
    for (const s of live.signals.slice().reverse()) {
      const row = el("div", "signal " + (s.level || "info"));
      const t = el("div", "s-time");
      t.appendChild(el("span", "", fmtTime(s.time)));
      t.appendChild(el("span", "", esc(s.kind.replace(/_/g, " "))));
      row.appendChild(t);
      row.appendChild(el("div", "s-msg", esc(s.message)));
      row.appendChild(el("div", "s-match", `${esc(s.home)} x ${esc(s.away)} · ${esc(s.league || "")} · ${s.minute ? s.minute + "'" : ""}`));
      list.appendChild(row);
    }
  }
  left.appendChild(list);
  layout.appendChild(left);

  // live matches
  const right = el("div", "panel");
  const head2 = el("div", "panel-head");
  head2.appendChild(el("h2", "", "🟢 Jogos ao vivo"));
  head2.appendChild(el("div", "sub", `${live.live_matches ? live.live_matches.length : 0} partidas`));
  right.appendChild(head2);

  if (!live.live_matches || !live.live_matches.length) {
    right.appendChild(el("div", "empty", "Nenhum jogo ao vivo agora."));
  } else {
    const tbl = el("table", "live-table");
    const thead = el("thead");
    const trh = el("tr");
    ["Min", "Partida", "Placar", "Cantos", "Chutes", "Posse", "xG"].forEach((h) => trh.appendChild(el("th", "", h)));
    thead.appendChild(trh);
    tbl.appendChild(thead);
    const tbody = el("tbody");
    for (const m of live.live_matches) {
      const tr = el("tr");
      tr.appendChild(el("td", "live", esc(String(m.minute || "")) + "'"));
      const name = el("td");
      const nm = m.url ? el("a", "", `${esc(m.home)} x ${esc(m.away)}`) : el("span", "", `${esc(m.home)} x ${esc(m.away)}`);
      if (m.url) nm.href = m.url;
      nm.target = "_blank";
      nm.rel = "noopener";
      name.appendChild(nm);
      tr.appendChild(name);
      tr.appendChild(el("td", "", `${m.score_home ?? "-"} x ${m.score_away ?? "-"}`));
      tr.appendChild(el("td", "", m.corners_home != null ? `${m.corners_home}-${m.corners_away}` : "-"));
      tr.appendChild(el("td", "", m.shots_on_home != null ? `${m.shots_on_home}-${m.shots_on_away}` : "-"));
      tr.appendChild(el("td", "", m.possession_home != null ? `${m.possession_home}%` : "-"));
      tr.appendChild(el("td", "", m.xg_home != null ? `${m.xg_home}-${m.xg_away}` : "-"));
      tbody.appendChild(tr);
    }
    tbl.appendChild(tbody);
    right.appendChild(tbl);
  }
  layout.appendChild(right);
  box.appendChild(layout);

  if (live.error) {
    box.appendChild(el("div", "errorbox", `Erro no feed ao vivo: ${esc(live.error)}`));
  }
}

/* ---------------- main ---------------- */

function renderAll() {
  if (!state) return;
  renderToday(state);
  renderAcca(state);
  renderYoutube(state);
  renderLive(state);
  $("#sourceChips").replaceChildren(sourceChips(state.predictions.sources));
  $("#updatedAt").textContent = "atualizado " + fmtWhen(state.predictions.generated_at);
}

async function loadAll(manual = false) {
  const btn = $("#btnRefresh");
  if (manual) btn.disabled = true;
  try {
    if (window.__SNAPSHOT__) {
      // static preview mode: data embedded in the page
      state = window.__SNAPSHOT__;
      renderAll();
      return;
    }
    const res = await fetch("/api/overview", { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    state = await res.json();
    renderAll();
  } catch (err) {
    const box = $("#todayContent");
    box.innerHTML = "";
    box.appendChild(el("div", "errorbox", "Falha ao carregar dados: " + esc(err.message)));
  } finally {
    if (manual) btn.disabled = false;
  }
}

async function loadLiveOnly() {
  try {
    const res = await fetch("/api/live", { cache: "no-store" });
    if (!res.ok) return;
    const live = await res.json();
    if (state) {
      state.live = live;
      renderLive(state);
    }
  } catch (e) { /* silencioso */ }
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".tabpanel").forEach((p) => p.classList.toggle("active", p.id === "tab-" + name));
  if (name === "live" && !window.__SNAPSHOT__) {
    // live polling only makes sense against a running server
    loadLiveOnly();
    if (!liveTimer) liveTimer = setInterval(loadLiveOnly, 45000);
  }
}

document.querySelectorAll(".tab").forEach((t) => {
  t.addEventListener("click", () => switchTab(t.dataset.tab));
});
$("#btnRefresh").addEventListener("click", () => loadAll(true));

// full refresh every 3 minutes
setInterval(() => loadAll(false), 180000);

loadAll(false);
