class MediaDownloader {
  constructor() {
    // YouTube search service URL (deployed on Fly.io)
    this.YOUTUBE_SEARCH_URL = "https://p01--yts--wv25f6hgmh8b.code.run"
    // Cycling status messages for long downloads
    this.statusMessages = ["Fetching media...", "Downloading...", "Almost there...", "Finalizing..."]
    this.statusTimers = {}
    this.initEventListeners()
  }

  initEventListeners() {
    const hamburger = document.getElementById("hamburger")
    const navMenu = document.getElementById("nav-menu")

    if (hamburger && navMenu) {
      hamburger.addEventListener("click", () => {
        hamburger.classList.toggle("active")
        navMenu.classList.toggle("active")
      })

      document.querySelectorAll(".nav-link").forEach((n) =>
        n.addEventListener("click", () => {
          hamburger.classList.remove("active")
          navMenu.classList.remove("active")
        }),
      )
    }

    const faqItems = document.querySelectorAll(".faq-item")
    faqItems.forEach((item) => {
      const question = item.querySelector(".faq-question")
      question.addEventListener("click", () => {
        const isActive = item.classList.contains("active")
        faqItems.forEach((faq) => faq.classList.remove("active"))
        if (!isActive) item.classList.add("active")
      })
    })

    // FIX #5: Enter key on YouTube search (already existed) + all URL inputs
    const youtubeSearch = document.getElementById("youtube-search")
    if (youtubeSearch) {
      youtubeSearch.addEventListener("keypress", (e) => {
        if (e.key === "Enter") this.searchYouTube()
      })
    }

    // FIX #5: Enter key on all URL paste inputs
    const urlInputs = ["youtube-url", "tiktok-url", "instagram-url", "facebook-url", "x-url"]
    urlInputs.forEach((id) => {
      const el = document.getElementById(id)
      if (el) {
        el.addEventListener("keypress", (e) => {
          if (e.key === "Enter") {
            const platform = id.replace("-url", "")
            this.download(platform)
          }
        })
      }
    })

    // FIX #7: Dynamic copyright year
    const copyrightEl = document.getElementById("footer-copyright")
    if (copyrightEl) {
      copyrightEl.textContent = `© ${new Date().getFullYear()} Mbuvi Tech. All rights reserved.`
    }
  }

  updateYouTubeQuality() {
    const type = document.getElementById("youtube-type").value
    const qualitySelect = document.getElementById("youtube-quality")
    qualitySelect.innerHTML = ""
    const options = type === "video" ? ["360p", "480p", "720p", "1080p"] : ["128K", "192K", "320K"]
    options.forEach((opt) => {
      const option = document.createElement("option")
      option.value = opt
      option.textContent = opt
      qualitySelect.appendChild(option)
    })
  }

  // FIX #17: Toast notification system — replaces per-card error/success divs
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
      <i class="fas ${type === "success" ? "fa-check-circle" : "fa-exclamation-circle"}"></i>
      <span>${message}</span>
      <button class="toast-close" onclick="this.parentElement.remove()"><i class="fas fa-times"></i></button>
    `
    container.appendChild(toast)

    // Animate in
    requestAnimationFrame(() => toast.classList.add("toast-visible"))

    // Auto-remove after 5s
    setTimeout(() => {
      toast.classList.remove("toast-visible")
      setTimeout(() => toast.remove(), 400)
    }, 5000)
  }

  showError(platform, message) {
    // Keep inline error for accessibility, but also show toast
    const errorElement = document.getElementById(`${platform}-error`)
    if (errorElement) {
      errorElement.textContent = message
      errorElement.style.display = "block"
      setTimeout(() => { errorElement.style.display = "none" }, 5000)
    }
    this.showToast(message, "error")
  }

  clearInputs(platform) {
    const urlInput = document.getElementById(`${platform}-url`)
    if (urlInput) urlInput.value = ""

    if (platform === "youtube") {
      const searchInput = document.getElementById("youtube-search")
      if (searchInput) searchInput.value = ""
    }

    const typeSelect = document.getElementById(`${platform}-type`)
    if (typeSelect) typeSelect.selectedIndex = 0

    const qualitySelect = document.getElementById(`${platform}-quality`)
    if (qualitySelect) qualitySelect.selectedIndex = 0
  }

  // FIX #6: Cycling status messages
  startStatusCycle(platform) {
    const statusElement = document.getElementById(`${platform}-download-status`)
    if (!statusElement) return
    const textSpan = statusElement.querySelector("span")
    if (!textSpan) return

    let idx = 0
    textSpan.textContent = this.statusMessages[0]

    this.statusTimers[platform] = setInterval(() => {
      idx = (idx + 1) % this.statusMessages.length
      textSpan.textContent = this.statusMessages[idx]
    }, 6000)
  }

  stopStatusCycle(platform) {
    if (this.statusTimers[platform]) {
      clearInterval(this.statusTimers[platform])
      delete this.statusTimers[platform]
    }
  }

  showDownloadStatus(platform) {
    const statusElement = document.getElementById(`${platform}-download-status`)
    const successElement = document.getElementById(`${platform}-success`)
    if (successElement) successElement.style.display = "none"
    if (statusElement) {
      statusElement.style.display = "flex"
      // FIX #16: Scroll status into view on mobile
      statusElement.scrollIntoView({ behavior: "smooth", block: "nearest" })
    }
    this.startStatusCycle(platform)
  }

  showDownloadSuccess(platform) {
    this.stopStatusCycle(platform)
    const statusElement = document.getElementById(`${platform}-download-status`)
    const successElement = document.getElementById(`${platform}-success`)
    if (statusElement) statusElement.style.display = "none"
    if (successElement) {
      successElement.style.display = "flex"
      setTimeout(() => { successElement.style.display = "none" }, 5000)
    }
    this.showToast("Downloaded successfully! 🎉", "success")
  }

  async pasteFromClipboard(inputId) {
    try {
      const text = await navigator.clipboard.readText()
      document.getElementById(inputId).value = text
      const input = document.getElementById(inputId)
      const originalBorder = input.style.borderColor
      input.style.borderColor = "#48bb78"
      setTimeout(() => { input.style.borderColor = originalBorder }, 1000)
    } catch (err) {
      console.log("Clipboard access not available")
      const platform = inputId.split("-")[0]
      this.showError(platform, "Please paste the URL manually")
    }
  }

  async searchYouTube() {
    const query = document.getElementById("youtube-search").value.trim()
    const loading = document.getElementById("youtube-loading")

    if (!query) {
      this.showError("youtube", "Please enter a song name")
      return
    }

    loading.style.display = "flex"

    try {
      const response = await fetch(`${this.YOUTUBE_SEARCH_URL}/api/ytsearch?q=${encodeURIComponent(query)}`)
      const data = await response.json()
      if (data.url) {
        document.getElementById("youtube-url").value = data.url
        document.getElementById("youtube-search").value = ""
      } else {
        this.showError("youtube", data.error || "Song not found")
      }
    } catch (err) {
      this.showError("youtube", "Search failed - Make sure YouTube search service is running")
    } finally {
      loading.style.display = "none"
    }
  }

  validateURL(platform, url) {
    const patterns = {
      youtube: /^https?:\/\/(www\.)?(youtube\.com|youtu\.be)\/.+/,
      // FIX #3: Added vt.tiktok.com to the TikTok pattern
      tiktok: /^https?:\/\/(www\.)?(tiktok\.com|vm\.tiktok\.com|vt\.tiktok\.com)\/.+/,
      instagram: /^https?:\/\/(www\.)?instagram\.com\/.+/,
      facebook: /^https?:\/\/(www\.)?facebook\.com\/.+/,
      x: /^https?:\/\/(www\.)?(twitter\.com|x\.com)\/.+/,
    }
    return patterns[platform].test(url)
  }

  // FIX #4: Parse JSON error body from server responses
  async downloadFile(url) {
    const response = await fetch(url)

    if (!response.ok) {
      let errorMsg = `HTTP ${response.status}`
      try {
        const contentType = response.headers.get("Content-Type") || ""
        if (contentType.includes("application/json")) {
          const errJson = await response.json()
          errorMsg = errJson.detail || errJson.error || errJson.message || errorMsg
        } else {
          const errText = await response.text()
          errorMsg = errText || errorMsg
        }
      } catch (_) { /* ignore parse errors */ }
      throw new Error(errorMsg)
    }

    const contentDisposition = response.headers.get("Content-Disposition")
    let filename = "download"

    if (contentDisposition) {
      const filenameMatch = contentDisposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/)
      if (filenameMatch) {
        filename = filenameMatch[1].replace(/['"]/g, "")
      }
    }

    const blob = await response.blob()
    const downloadUrl = window.URL.createObjectURL(blob)

    const a = document.createElement("a")
    a.href = downloadUrl
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)

    window.URL.revokeObjectURL(downloadUrl)
    return true
  }

  async download(platform) {
    const urlElement = document.getElementById(`${platform}-url`)
    const url = urlElement.value.trim()

    if (!url) return this.showError(platform, "Please enter a URL")
    if (!this.validateURL(platform, url)) return this.showError(platform, `Invalid ${platform} URL`)

    const button = document.querySelector(`.${platform}-btn`)
    const btnText = button.querySelector("span")
    const btnIcon = button.querySelector("i")

    const originalText = btnText.textContent
    const originalIcon = btnIcon.className

    btnText.textContent = "Downloading..."
    btnIcon.className = "fas fa-spinner fa-spin"
    button.disabled = true

    try {
      const downloadUrl = this.buildHybridDownloadUrl(platform, url)
      this.showDownloadStatus(platform)

      // FIX #1: YouTube now uses the same fetch-based downloadFile() approach
      await this.downloadFile(downloadUrl)
      this.showDownloadSuccess(platform)
      this.clearInputs(platform)
    } catch (error) {
      this.stopStatusCycle(platform)
      const statusElement = document.getElementById(`${platform}-download-status`)
      if (statusElement) statusElement.style.display = "none"
      this.showError(platform, `Download failed: ${error.message}`)
    } finally {
      btnText.textContent = originalText
      btnIcon.className = originalIcon
      button.disabled = false
    }
  }

  buildHybridDownloadUrl(platform, url) {
    const encodedUrl = encodeURIComponent(url)

    switch (platform) {
      case "youtube": {
        const type = document.getElementById("youtube-type").value
        const quality = document.getElementById("youtube-quality").value
        if (type === "audio") {
          return `/download/audio/stream?song=${encodedUrl}&quality=${quality}`
        } else {
          return `/download/video/stream?song=${encodedUrl}&quality=${quality}`
        }
      }
      case "x":
        return `/stream/xurl?url=${encodedUrl}`

      case "tiktok": {
        const tiktokType = document.getElementById("tiktok-type").value
        const endpoint = tiktokType === "video" ? "tiktokurl" : "tiktoaudio"
        return `/api/${endpoint}?url=${encodedUrl}`
      }
      case "instagram":
        return `/download/iglink?url=${encodedUrl}`

      case "facebook":
        return `/api/fburl?url=${encodedUrl}`

      default:
        throw new Error("Unsupported platform")
    }
  }

  // FIX #2: buildDownloadUrl() removed (was dead code — replaced by buildHybridDownloadUrl)

  getDownloadMethod(platform) {
    const methods = {
      youtube: "🚀 Fast (fetch-based with browser progress)",
      x: "🚀 Fast (fetch-based with browser progress)",
      tiktok: "📁 File-based (Reliable for TikTok)",
      instagram: "📁 File-based (Reliable for secure platform)",
      facebook: "📁 File-based (Reliable for secure platform)",
    }
    return methods[platform] || "Unknown"
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const downloader = new MediaDownloader()

  window.updateYouTubeQuality = () => downloader.updateYouTubeQuality()
  window.pasteFromClipboard = (inputId) => downloader.pasteFromClipboard(inputId)
  window.searchYouTube = () => downloader.searchYouTube()
  window.download = (platform) => downloader.download(platform)

  downloader.updateYouTubeQuality()

  console.log("🔧 Download Methods:")
  console.log("YouTube:", downloader.getDownloadMethod("youtube"))
  console.log("X/Twitter:", downloader.getDownloadMethod("x"))
  console.log("TikTok:", downloader.getDownloadMethod("tiktok"))
  console.log("Instagram:", downloader.getDownloadMethod("instagram"))
  console.log("Facebook:", downloader.getDownloadMethod("facebook"))
})
