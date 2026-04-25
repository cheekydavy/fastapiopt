class MediaDownloader {
  constructor() {
    this.YOUTUBE_SEARCH_URL = "https://p01--yts--wv25f6hgmh8b.code.run"
    this.statusMessages = ["Fetching media…", "Downloading…", "Almost there…", "Finalizing…"]
    this.statusTimers = {}
    this.initEventListeners()
  }

  initEventListeners() {
    // Hamburger nav toggle
    const hamburger = document.getElementById("hamburger")
    const navMenu   = document.getElementById("nav-menu")
    if (hamburger && navMenu) {
      hamburger.addEventListener("click", () => {
        const open = hamburger.classList.toggle("active")
        navMenu.classList.toggle("active", open)
        hamburger.setAttribute("aria-expanded", open)
      })
      document.querySelectorAll(".nav-link").forEach(n =>
        n.addEventListener("click", () => {
          hamburger.classList.remove("active")
          navMenu.classList.remove("active")
          hamburger.setAttribute("aria-expanded", "false")
        })
      )
    }

    // FAQ — handled natively by <details>/<summary>, no JS needed

    // Enter key on YouTube search
    const youtubeSearch = document.getElementById("youtube-search")
    if (youtubeSearch) {
      youtubeSearch.addEventListener("keypress", e => {
        if (e.key === "Enter") this.searchYouTube()
      })
    }

    // Enter key on all URL inputs
    const urlInputs = ["youtube-url", "tiktok-url", "instagram-url", "facebook-url", "x-url"]
    urlInputs.forEach(id => {
      const el = document.getElementById(id)
      if (el) {
        el.addEventListener("keypress", e => {
          if (e.key === "Enter") {
            const platform = id.replace("-url", "")
            this.download(platform)
          }
        })
      }
    })

    // Dynamic copyright year
    const copyrightEl = document.getElementById("footer-copyright")
    if (copyrightEl) {
      copyrightEl.textContent = `© ${new Date().getFullYear()} Mbuvi Tech. All rights reserved.`
    }
  }

  // ── YouTube quality options ──────────────────────────────
  updateYouTubeQuality() {
    const type    = document.getElementById("youtube-type").value
    const select  = document.getElementById("youtube-quality")
    select.innerHTML = ""
    // Audio is default (first option in HTML), so audio qualities load first
    const options = type === "audio"
      ? ["128K", "192K", "320K"]
      : ["360p", "480p", "720p", "1080p"]
    options.forEach(opt => {
      const o = document.createElement("option")
      o.value = o.textContent = opt
      select.appendChild(o)
    })
  }

  // ── Toast ────────────────────────────────────────────────
  showToast(message, type = "error") {
    let container = document.getElementById("toast-container")
    if (!container) {
      container = document.createElement("div")
      container.id = "toast-container"
      document.body.appendChild(container)
    }
    const toast = document.createElement("div")
    toast.className = `toast toast-${type}`
    toast.innerHTML = `
      <i class="fas ${type === "success" ? "fa-check-circle" : "fa-exclamation-circle"}" aria-hidden="true"></i>
      <span>${message}</span>
      <button class="toast-close" aria-label="Dismiss" onclick="this.parentElement.remove()">
        <i class="fas fa-times" aria-hidden="true"></i>
      </button>`
    container.appendChild(toast)
    requestAnimationFrame(() => toast.classList.add("toast-visible"))
    setTimeout(() => {
      toast.classList.remove("toast-visible")
      setTimeout(() => toast.remove(), 400)
    }, 5000)
  }

  // ── Error / status helpers ───────────────────────────────
  showError(platform, message) {
    const el = document.getElementById(`${platform}-error`)
    if (el) {
      el.textContent = message
      el.hidden = false
      setTimeout(() => { el.hidden = true }, 6000)
    }
    this.showToast(message, "error")
  }

  clearInputs(platform) {
    const urlInput = document.getElementById(`${platform}-url`)
    if (urlInput) urlInput.value = ""
    if (platform === "youtube") {
      const s = document.getElementById("youtube-search")
      if (s) s.value = ""
    }
    const typeSelect    = document.getElementById(`${platform}-type`)
    const qualitySelect = document.getElementById(`${platform}-quality`)
    if (typeSelect)    typeSelect.selectedIndex = 0
    if (qualitySelect) qualitySelect.selectedIndex = 0
  }

  // ── Cycling status messages ──────────────────────────────
  startStatusCycle(platform) {
    const el   = document.getElementById(`${platform}-download-status`)
    if (!el) return
    const span = el.querySelector("span:last-child")
    if (!span) return
    let idx = 0
    span.textContent = this.statusMessages[0]
    this.statusTimers[platform] = setInterval(() => {
      idx = (idx + 1) % this.statusMessages.length
      span.textContent = this.statusMessages[idx]
    }, 6000)
  }

  stopStatusCycle(platform) {
    if (this.statusTimers[platform]) {
      clearInterval(this.statusTimers[platform])
      delete this.statusTimers[platform]
    }
  }

  showDownloadStatus(platform) {
    const statusEl  = document.getElementById(`${platform}-download-status`)
    const successEl = document.getElementById(`${platform}-success`)
    if (successEl) successEl.hidden = true
    if (statusEl) {
      statusEl.hidden = false
      statusEl.scrollIntoView({ behavior: "smooth", block: "nearest" })
    }
    this.startStatusCycle(platform)
  }

  showDownloadSuccess(platform) {
    this.stopStatusCycle(platform)
    const statusEl  = document.getElementById(`${platform}-download-status`)
    const successEl = document.getElementById(`${platform}-success`)
    if (statusEl)  statusEl.hidden = true
    if (successEl) {
      successEl.hidden = false
      setTimeout(() => { successEl.hidden = true }, 5000)
    }
    this.showToast("Downloaded successfully! 🎉", "success")
  }

  // ── Clipboard paste ──────────────────────────────────────
  async pasteFromClipboard(inputId) {
    try {
      const text  = await navigator.clipboard.readText()
      const input = document.getElementById(inputId)
      input.value = text
      input.style.borderColor = "var(--ok)"
      setTimeout(() => { input.style.borderColor = "" }, 1200)
    } catch {
      const platform = inputId.split("-")[0]
      this.showError(platform, "Clipboard access denied — paste manually.")
    }
  }

  // ── YouTube search ───────────────────────────────────────
  async searchYouTube() {
    const query   = document.getElementById("youtube-search").value.trim()
    const loader  = document.getElementById("youtube-loading")
    if (!query) { this.showError("youtube", "Enter a song name to search"); return }

    loader.hidden = false
    loader.setAttribute("aria-busy", "true")
    try {
      const res  = await fetch(`${this.YOUTUBE_SEARCH_URL}/api/ytsearch?q=${encodeURIComponent(query)}`)
      const data = await res.json()
      if (data.url) {
        document.getElementById("youtube-url").value    = data.url
        document.getElementById("youtube-search").value = ""
      } else {
        this.showError("youtube", data.error || "Song not found")
      }
    } catch {
      this.showError("youtube", "Search failed — check your connection")
    } finally {
      loader.hidden = true
      loader.setAttribute("aria-busy", "false")
    }
  }

  // ── URL validation ───────────────────────────────────────
  validateURL(platform, url) {
    const patterns = {
      youtube:   /^https?:\/\/(www\.)?(youtube\.com|youtu\.be)\/.+/,
      tiktok:    /^https?:\/\/(www\.)?(tiktok\.com|vm\.tiktok\.com|vt\.tiktok\.com)\/.+/,
      instagram: /^https?:\/\/(www\.)?instagram\.com\/.+/,
      facebook:  /^https?:\/\/(www\.)?facebook\.com\/.+/,
      x:         /^https?:\/\/(www\.)?(twitter\.com|x\.com)\/.+/,
    }
    return patterns[platform].test(url)
  }

  // ── Fetch download with proper error parsing ─────────────
  async downloadFile(url) {
    const response = await fetch(url)
    if (!response.ok) {
      let msg = `HTTP ${response.status}`
      try {
        const ct = response.headers.get("Content-Type") || ""
        if (ct.includes("application/json")) {
          const j = await response.json()
          msg = j.detail || j.error || j.message || msg
        } else {
          msg = (await response.text()) || msg
        }
      } catch { /* ignore */ }
      throw new Error(msg)
    }

    const cd = response.headers.get("Content-Disposition") || ""
    const m  = cd.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/)
    const filename = m ? m[1].replace(/['"]/g, "") : "download"

    const blob = await response.blob()
    const a    = document.createElement("a")
    a.href     = window.URL.createObjectURL(blob)
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(a.href)
    return true
  }

  // ── Main download handler ────────────────────────────────
  async download(platform) {
    const urlEl = document.getElementById(`${platform}-url`)
    const url   = urlEl.value.trim()

    if (!url)                             return this.showError(platform, "Please enter a URL")
    if (!this.validateURL(platform, url)) return this.showError(platform, `Invalid ${platform} URL`)

    const btn     = document.querySelector(`.${platform}-btn`)
    const btnText = btn.querySelector("span:last-child")
    const btnIcon = btn.querySelector("i")

    const origText = btnText.textContent
    const origIcon = btnIcon.className

    btnText.textContent = "Downloading…"
    btnIcon.className   = "fas fa-spinner fa-spin"
    btn.disabled        = true

    try {
      this.showDownloadStatus(platform)
      await this.downloadFile(this.buildDownloadUrl(platform, url))
      this.showDownloadSuccess(platform)
      this.clearInputs(platform)
    } catch (err) {
      this.stopStatusCycle(platform)
      const statusEl = document.getElementById(`${platform}-download-status`)
      if (statusEl) statusEl.hidden = true
      this.showError(platform, `Download failed: ${err.message}`)
    } finally {
      btnText.textContent = origText
      btnIcon.className   = origIcon
      btn.disabled        = false
    }
  }

  // ── Build endpoint URL ───────────────────────────────────
  buildDownloadUrl(platform, url) {
    const enc = encodeURIComponent(url)
    switch (platform) {
      case "youtube": {
        const type    = document.getElementById("youtube-type").value
        const quality = document.getElementById("youtube-quality").value
        return type === "audio"
          ? `/download/audio/stream?song=${enc}&quality=${quality}`
          : `/download/video/stream?song=${enc}&quality=${quality}`
      }
      case "x":
        return `/stream/xurl?url=${enc}`
      case "tiktok": {
        const t = document.getElementById("tiktok-type").value
        return `/api/${t === "video" ? "tiktokurl" : "tiktoaudio"}?url=${enc}`
      }
      case "instagram":
        return `/download/iglink?url=${enc}`
      case "facebook":
        return `/api/fburl?url=${enc}`
      default:
        throw new Error("Unsupported platform")
    }
  }
}

// ── Boot ─────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  const dl = new MediaDownloader()

  window.updateYouTubeQuality  = ()      => dl.updateYouTubeQuality()
  window.pasteFromClipboard    = inputId => dl.pasteFromClipboard(inputId)
  window.searchYouTube         = ()      => dl.searchYouTube()
  window.download              = p       => dl.download(p)

  // Populate quality dropdown — audio is the default type
  dl.updateYouTubeQuality()
})
