// QOBUZ-DL // CLEAN FRONTEND LOGIC

let currentAlbumData = null;
let queueData = { active: [], completed: [], failed: [] };
let searchDebounceTimer = null;

document.addEventListener("DOMContentLoaded", () => {
  initWebSocket();
  loadReleases();
  loadConfig();
  initEventListeners();
});

// WEBSOCKET INITIALIZATION
function initWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws/live`;
  const ws = new WebSocket(wsUrl);

  ws.onmessage = (event) => {
    try {
      const msg = jsonSafeParse(event.data);
      if (!msg) return;
      if (msg.type === "init" || msg.type === "tick" || msg.type === "queue_update" || msg.type === "item_update") {
        updateActiveStatus(msg.data?.active_items || []);
      }
    } catch (e) {}
  };

  ws.onclose = () => {
    setTimeout(initWebSocket, 2000);
  };
}

function jsonSafeParse(str) {
  try { return JSON.parse(str); } catch (e) { return null; }
}

// LOAD RECENT RELEASES
async function loadReleases() {
  const grid = document.getElementById("releasesGrid");
  const countLabel = document.getElementById("releasesCount");
  try {
    const res = await fetch("/api/get-releases?limit=24");
    const data = await res.json();
    const items = data.albums?.items || [];
    
    countLabel.textContent = `${items.length} álbuns em destaque`;
    grid.innerHTML = "";

    items.forEach(album => {
      const card = document.createElement("div");
      card.className = "release-card";
      const cover = album.image?.large || album.image?.small || "/static/favicon.ico";
      const hiresBadge = (album.maximum_bit_depth > 16) ? `${album.maximum_bit_depth}B • ${album.maximum_sampling_rate}kHz` : "CD FLAC";
      const year = (album.release_date_original || "").substring(0, 4) || "2024";

      card.innerHTML = `
        <div class="card-cover-wrapper">
          <img src="${cover}" class="card-cover" alt="${album.title}" loading="lazy">
          <span class="card-quality-badge">${hiresBadge}</span>
        </div>
        <div class="card-body">
          <div class="card-title" title="${album.title}">${album.title}</div>
          <div class="card-artist" title="${album.artist?.name}">${album.artist?.name}</div>
          <div class="card-meta">${year} • ${album.tracks_count || 10} faixas</div>
        </div>
      `;

      card.addEventListener("click", () => openAlbumModal(album.id));
      grid.appendChild(card);
    });
  } catch (e) {
    countLabel.textContent = "Erro ao carregar lançamentos";
  }
}

// SEARCH & AUTOCOMPLETE
const searchInput = document.getElementById("searchInput");
const autocompleteDropdown = document.getElementById("autocompleteDropdown");

searchInput.addEventListener("input", (e) => {
  const val = e.target.value.trim();
  clearTimeout(searchDebounceTimer);

  if (!val) {
    autocompleteDropdown.style.display = "none";
    return;
  }

  // If user pastes direct Qobuz URL
  if (val.includes("qobuz.com/")) {
    handleUrlPaste(val);
    return;
  }

  searchDebounceTimer = setTimeout(async () => {
    try {
      const res = await fetch(`/api/search?q=${encodeURIComponent(val)}&limit=8`);
      const data = await res.json();
      renderAutocomplete(data);
    } catch (err) {}
  }, 250);
});

function renderAutocomplete(data) {
  autocompleteDropdown.innerHTML = "";
  const tracks = data.tracks?.items || [];
  const albums = data.albums?.items || [];

  if (tracks.length === 0 && albums.length === 0) {
    autocompleteDropdown.style.display = "none";
    return;
  }

  // Render albums
  albums.slice(0, 4).forEach(a => {
    const item = document.createElement("div");
    item.className = "autocomplete-item";
    const thumb = a.image?.small || a.image?.thumbnail || "/static/favicon.ico";
    item.innerHTML = `
      <div class="item-left">
        <img src="${thumb}" class="item-thumb">
        <div class="item-info">
          <div class="item-title">${a.title}</div>
          <div class="item-sub">Álbum • ${a.artist?.name}</div>
        </div>
      </div>
      <button class="btn btn-secondary" style="padding: 4px 10px; font-size: 11px;">Ver</button>
    `;
    item.addEventListener("click", () => {
      autocompleteDropdown.style.display = "none";
      openAlbumModal(a.id);
    });
    autocompleteDropdown.appendChild(item);
  });

  // Render tracks
  tracks.slice(0, 5).forEach(t => {
    const item = document.createElement("div");
    item.className = "autocomplete-item";
    const thumb = t.album?.image?.small || "/static/favicon.ico";
    item.innerHTML = `
      <div class="item-left">
        <img src="${thumb}" class="item-thumb">
        <div class="item-info">
          <div class="item-title">${t.title}</div>
          <div class="item-sub">Faixa • ${t.performer?.name || t.album?.artist?.name}</div>
        </div>
      </div>
      <button class="btn btn-primary" style="padding: 4px 10px; font-size: 11px;">Baixar</button>
    `;
    item.addEventListener("click", () => {
      autocompleteDropdown.style.display = "none";
      enqueueItem(`https://open.qobuz.com/track/${t.id}`);
    });
    autocompleteDropdown.appendChild(item);
  });

  autocompleteDropdown.style.display = "block";
}

document.addEventListener("click", (e) => {
  if (!searchInput.contains(e.target) && !autocompleteDropdown.contains(e.target)) {
    autocompleteDropdown.style.display = "none";
  }
});

async function handleUrlPaste(url) {
  try {
    enqueueItem(url);
    searchInput.value = "";
    autocompleteDropdown.style.display = "none";
  } catch (e) {}
}

// ALBUM MODAL
async function openAlbumModal(albumId) {
  const modal = document.getElementById("albumModal");
  modal.style.display = "flex";

  try {
    const res = await fetch(`/api/get-album?id=${albumId}`);
    const data = await res.json();
    currentAlbumData = data;

    document.getElementById("modalAlbumCover").src = data.image?.large || data.image?.small || "";
    document.getElementById("modalAlbumTitle").textContent = data.title;
    document.getElementById("modalAlbumArtist").textContent = data.artist?.name;
    const hiresBadge = (data.maximum_bit_depth > 16) ? `${data.maximum_bit_depth}-Bit / ${data.maximum_sampling_rate} kHz` : "16-Bit / 44.1 kHz";
    document.getElementById("modalAlbumMeta").textContent = `${(data.release_date_original||"2024").substring(0,4)} • ${data.tracks_count} faixas • FLAC ${hiresBadge}`;

    const tbody = document.getElementById("modalTracklistBody");
    tbody.innerHTML = "";

    const tracks = data.tracks?.items || [];
    tracks.forEach((t, idx) => {
      const tr = document.createElement("tr");
      const mins = Math.floor(t.duration / 60);
      const secs = String(t.duration % 60).padStart(2, "0");
      tr.innerHTML = `
        <td style="color: var(--text-dim);">${t.track_number || (idx + 1)}</td>
        <td style="font-weight: 500;">${t.title}</td>
        <td style="color: var(--text-muted);">${mins}:${secs}</td>
        <td><span class="card-quality-badge" style="position: static;">FLAC</span></td>
        <td style="text-align: right;">
          <button class="btn btn-secondary" style="padding: 4px 10px; font-size: 11px;">Baixar</button>
        </td>
      `;
      tr.querySelector("button").addEventListener("click", () => {
        enqueueItem(`https://open.qobuz.com/track/${t.id}`);
      });
      tbody.appendChild(tr);
    });

    document.getElementById("btnDownloadFullAlbum").onclick = () => {
      enqueueItem(`https://open.qobuz.com/album/${data.id}`);
      modal.style.display = "none";
    };
  } catch (e) {}
}

document.getElementById("btnCloseAlbumModal").addEventListener("click", () => {
  document.getElementById("albumModal").style.display = "none";
});

// ENQUEUE HELPER
async function enqueueItem(url) {
  try {
    const res = await fetch("/api/queue/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ urls: [url] })
    });
    const result = await res.json();
    document.getElementById("statusBar").style.display = "flex";
  } catch (e) {}
}

// STATUS BAR & QUEUE DRAWER
function updateActiveStatus(activeItems) {
  const bar = document.getElementById("statusBar");
  const badge = document.getElementById("queueBadgeCount");
  badge.textContent = activeItems.length;

  if (!activeItems || activeItems.length === 0) {
    return;
  }

  bar.style.display = "flex";
  const item = activeItems[0];

  document.getElementById("statusTitle").textContent = item.title || "Baixando...";
  document.getElementById("statusArtist").textContent = item.artist || "Qobuz Lossless";
  document.getElementById("statusQuality").textContent = item.quality_str || "FLAC";
  if (item.cover_url) {
    document.getElementById("statusThumb").src = item.cover_url;
  }

  const pct = Math.min(100, Math.max(0, item.percent || 0));
  document.getElementById("progressBarFill").style.width = `${pct}%`;
  document.getElementById("statusPercent").textContent = `${Math.round(pct)}%`;
}

// QUEUE MODAL
document.getElementById("btnOpenQueue").addEventListener("click", async () => {
  const modal = document.getElementById("queueModal");
  modal.style.display = "flex";
  refreshQueueList();
});

document.getElementById("btnCloseQueueModal").addEventListener("click", () => {
  document.getElementById("queueModal").style.display = "none";
});

async function refreshQueueList() {
  const container = document.getElementById("queueListContainer");
  try {
    const res = await fetch("/api/queue");
    const data = await res.json();
    container.innerHTML = "";

    const all = [...data.active, ...data.completed.slice(0, 10), ...data.failed];
    if (all.length === 0) {
      container.innerHTML = "<div style="color: var(--text-dim); text-align: center; padding: 20px;">A fila está vazia.</div>";
      return;
    }

    all.forEach(item => {
      const row = document.createElement("div");
      row.style.cssText = "display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; background: #18181b; border: 1px solid var(--border); border-radius: 8px;";
      row.innerHTML = `
        <div>
          <div style="font-size: 13px; font-weight: 600;">${item.title || item.url}</div>
          <div style="font-size: 11px; color: var(--text-muted);">${item.artist || ""} • ${item.stage || item.status_label || item.status}</div>
        </div>
        <span class="card-quality-badge" style="position: static;">${item.quality_str || "FLAC"}</span>
      `;
      container.appendChild(row);
    });
  } catch (e) {}
}

document.getElementById("btnPauseQueue").addEventListener("click", async () => {
  await fetch("/api/queue/pause", { method: "POST" });
});
document.getElementById("btnResumeQueue").addEventListener("click", async () => {
  await fetch("/api/queue/resume", { method: "POST" });
});
document.getElementById("btnClearQueue").addEventListener("click", async () => {
  await fetch("/api/queue/clear", { method: "POST" });
  refreshQueueList();
});

// SETTINGS MODAL
document.getElementById("btnOpenSettings").addEventListener("click", () => {
  document.getElementById("settingsModal").style.display = "flex";
  updatePathPreview();
});

document.getElementById("btnCloseSettingsModal").addEventListener("click", () => {
  document.getElementById("settingsModal").style.display = "none";
});

document.querySelectorAll(".settings-tabs .tab-btn").forEach(btn => {
  btn.addEventListener("click", (e) => {
    document.querySelectorAll(".settings-tabs .tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-pane").forEach(p => p.style.display = "none");
    btn.classList.add("active");
    document.getElementById(btn.dataset.tab).style.display = "block";
  });
});

async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    const cfg = await res.json();
    document.getElementById("cfgFormatId").value = cfg.quality?.format_id || 27;
    document.getElementById("cfgArtRes").value = cfg.quality?.art_resolution || "original";
    document.getElementById("cfgSaveLrc").checked = cfg.quality?.save_lrc_file !== false;
    document.getElementById("cfgDownloadDir").value = cfg.paths?.download_dir || "./downloads";
    document.getElementById("cfgFolderTemplate").value = cfg.paths?.folder_format || "{artist}/{album} ({year}) [{quality}]";
    document.getElementById("cfgTrackTemplate").value = cfg.paths?.track_format || "{track_number:02d} - {title}";
    document.getElementById("cfgAuthToken").value = cfg.auth?.user_auth_token || "";
    document.getElementById("cfgAppId").value = cfg.auth?.app_id || "712108709";
    updatePathPreview();
  } catch (e) {}
}

async function updatePathPreview() {
  const folderTpl = document.getElementById("cfgFolderTemplate").value;
  const trackTpl = document.getElementById("cfgTrackTemplate").value;
  const dir = document.getElementById("cfgDownloadDir").value;

  try {
    const res = await fetch("/api/config/preview-path", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        artist: "Daft Punk",
        album: "Discovery",
        year: "2001",
        quality: "24B-96kHz",
        track_number: 1,
        title: "One More Time"
      })
    });
    const preview = await res.json();
    document.getElementById("pathPreviewBox").textContent = preview.full_path_preview || `${dir}/Daft Punk/2001 - Discovery/01 - One More Time.flac`;
  } catch (e) {}
}

document.getElementById("cfgFolderTemplate").addEventListener("input", updatePathPreview);
document.getElementById("cfgTrackTemplate").addEventListener("input", updatePathPreview);
document.getElementById("cfgDownloadDir").addEventListener("input", updatePathPreview);

document.getElementById("btnSaveSettings").addEventListener("click", async () => {
  const payload = {
    quality: {
      format_id: parseInt(document.getElementById("cfgFormatId").value),
      art_resolution: document.getElementById("cfgArtRes").value,
      save_lrc_file: document.getElementById("cfgSaveLrc").checked
    },
    paths: {
      download_dir: document.getElementById("cfgDownloadDir").value,
      folder_format: document.getElementById("cfgFolderTemplate").value,
      track_format: document.getElementById("cfgTrackTemplate").value
    },
    auth: {
      user_auth_token: document.getElementById("cfgAuthToken").value,
      app_id: document.getElementById("cfgAppId").value
    }
  };

  try {
    await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    document.getElementById("settingsModal").style.display = "none";
  } catch (e) {}
});

document.getElementById("btnFetchDynamicTokens").addEventListener("click", async () => {
  try {
    const res = await fetch("/api/auth/fetch-tokens", { method: "POST" });
    const data = await res.json();
    if (data.app_id) {
      document.getElementById("cfgAppId").value = data.app_id;
      alert("App ID e Secrets atualizados com sucesso!");
    }
  } catch (e) {}
});

function initEventListeners() {
  // Modal background clicks
  document.querySelectorAll(".modal-overlay").forEach(overlay => {
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) {
        overlay.style.display = "none";
      }
    });
  });
}
