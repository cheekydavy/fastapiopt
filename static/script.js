class MediaDownloader {
  constructor() {
    // YouTube search service URL (deployed on Fly.io)
    this.YOUTUBE_SEARCH_URL = "https://yts.fly.dev"
    this.initEventListeners()
  }

  initEventListeners() {
    // Hamburger menu functionality
    const hamburger = document.getElementById("hamburger")
    const navMenu = document.getElementById("nav-menu")

    if (hamburger && navMenu) {
      hamburger.addEventListener("click", () => {
        hamburger.classList.toggle("active")
        navMenu.classList.toggle("active")
      })

      // Close menu when clicking on a link
      document.querySelectorAll(".nav-link").forEach((n) =>
        n.addEventListener("click", () => {
          hamburger.classList.remove("active")
          navMenu.classList.remove("active")
        }),
      )
    }

    // FAQ toggle functionality
    const faqItems = document.querySelectorAll(".faq-item")
    faqItems.forEach((item) => {
      const question = item.querySelector(".faq-question")
      question.addEventListener("click", () => {
        const isActive = item.classList.contains("active")

        // Close all FAQ items
        faqItems.forEach((faq) => faq.classList.remove("active"))

        // Open clicked item if it wasn't active
        if (!isActive) {
          item.classList.add("active")
        }
      })
    })

    // Allow Enter key to trigger search
    const youtubeSearch = document.getElementById("youtube-search")
    if (youtubeSearch) {
      youtubeSearch.addEventListener("keypress", (e) => {
        if (e.key === "Enter") {
          this.searchYouTube()
        }
      })
    }
  }

  updateYouTubeQuality() {
    const type = document.getElementById("youtube-type").value
    const qualitySelect = document.getElementById("youtube-quality")
    qualitySelect.innerHTML = ""
    const options = type === "video" ? ["1080p", "720p", "480p", "360p"] : ["128K", "192K", "320K"]
    options.forEach((opt) => {
      const option = document.createElement("option")
      option.value = opt
      option.textContent = opt
      qualitySelect.appendChild(option)
    })
  }

  showError(platform, message) {
    const errorElement = document.getElementById(`${platform}-error`)
    errorElement.textContent = message
    errorElement.style.display = "block"
    setTimeout(() => {
      errorElement.style.display = "none"
    }, 5000)
  }

  clearInputs(platform) {
    // Clear URL input
    const urlInput = document.getElementById(`${platform}-url`)
    if (urlInput) urlInput.value = ""

    // Clear search input for YouTube
    if (platform === "youtube") {
      const searchInput = document.getElementById("youtube-search")
      if (searchInput) searchInput.value = ""
    }

    // Reset selects to default values
    const typeSelect = document.getElementById(`${platform}-type`)
    if (typeSelect) typeSelect.selectedIndex = 0

    const qualitySelect = document.getElementById(`${platform}-quality`)
    if (qualitySelect) qualitySelect.selectedIndex = 0
  }

  showDownloadStatus(platform) {
    const statusElement = document.getElementById(`${platform}-download-status`)
    const successElement = document.getElementById(`${platform}-success`)

    // Hide success message and show status
    if (successElement) successElement.style.display = "none"
    if (statusElement) statusElement.style.display = "flex"
  }

  showDownloadSuccess(platform) {
    const statusElement = document.getElementById(`${platform}-download-status`)
    const successElement = document.getElementById(`${platform}-success`)

    // Hide status and show success
    if (statusElement) statusElement.style.display = "none"
    if (successElement) {
      successElement.style.display = "flex"

      // Hide success message after 5 seconds
      setTimeout(() => {
        successElement.style.display = "none"
      }, 5000)
    }
  }

  async pasteFromClipboard(inputId) {
    try {
      const text = await navigator.clipboard.readText()
      document.getElementById(inputId).value = text

      // Show feedback
      const input = document.getElementById(inputId)
      const originalBorder = input.style.borderColor
      input.style.borderColor = "#48bb78"
      setTimeout(() => {
        input.style.borderColor = originalBorder
      }, 1000)
    } catch (err) {
      console.log("Clipboard access not available")
      // Fallback: show a message to manually paste
      this.showError(inputId.split("-")[0], "Please paste the URL manually")
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
      // Call Node.js service directly
      const response = await fetch(`${this.YOUTUBE_SEARCH_URL}/api/ytsearch?q=${encodeURIComponent(query)}`)
      const data = await response.json()
      if (data.url) {
        document.getElementById("youtube-url").value = data.url
        // Clear search field after successful search
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
      tiktok: /^https?:\/\/(www\.)?(tiktok\.com|vm\.tiktok\.com)\/.+/,
      instagram: /^https?:\/\/(www\.)?instagram\.com\/.+/,
      facebook: /^https?:\/\/(www\.)?facebook\.com\/.+/,
      x: /^https?:\/\/(www\.)?(twitter\.com|x\.com)\/.+/,
    }
    return patterns[platform].test(url)
  }

  async downloadFile(url) {
    const response = await fetch(url)

    if (!response.ok) {
      const errorText = await response.text()
      throw new Error(errorText || `HTTP ${response.status}`)
    }

    // Get filename from Content-Disposition header or URL
    const contentDisposition = response.headers.get("Content-Disposition")
    let filename = "download"

    if (contentDisposition) {
      const filenameMatch = contentDisposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/)
      if (filenameMatch) {
        filename = filenameMatch[1].replace(/['"]/g, "")
      }
    }

    // Create blob and download
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

    // Show loading state on button
    const button = document.querySelector(`.${platform}-btn`)
    const btnText = button.querySelector("span")
    const btnIcon = button.querySelector("i")

    const originalText = btnText.textContent
    const originalIcon = btnIcon.className

    btnText.textContent = "Downloading..."
    btnIcon.className = "fas fa-spinner fa-spin"
    button.disabled = true

    try {
      // Build the STREAMING download URL (faster)
      const downloadUrl = this.buildStreamingDownloadUrl(platform, url)

      // Show "Starting download..." when we hit the API
      this.showDownloadStatus(platform)

      // Use fetch for downloads
      await this.downloadFile(downloadUrl)

      // Show success and clear inputs
      this.showDownloadSuccess(platform)
      this.clearInputs(platform)
    } catch (error) {
      this.showError(platform, `Download failed: ${error.message}`)

      // Hide download status on error
      const statusElement = document.getElementById(`${platform}-download-status`)
      if (statusElement) statusElement.style.display = "none"
    } finally {
      // Reset button
      btnText.textContent = originalText
      btnIcon.className = originalIcon
      button.disabled = false
    }
  }

  buildStreamingDownloadUrl(platform, url) {
    const encodedUrl = encodeURIComponent(url)

    switch (platform) {
      case "youtube":
        const type = document.getElementById("youtube-type").value
        const quality = document.getElementById("youtube-quality").value
        // Use NEW streaming endpoints for faster downloads
        return `/stream/${type}?song=${encodedUrl}&quality=${quality}`

      case "tiktok":
        const tiktokType = document.getElementById("tiktok-type").value
        const endpoint = tiktokType === "video" ? "tiktokurl" : "tiktoaudio"
        // Use NEW streaming endpoints for faster downloads
        return `/stream/${endpoint}?url=${encodedUrl}`

      case "instagram":
        // Use NEW streaming endpoint for faster downloads
        return `/stream/iglink?url=${encodedUrl}`

      case "facebook":
        // Use NEW streaming endpoint for faster downloads
        return `/stream/fburl?url=${encodedUrl}`

      case "x":
        // Use NEW streaming endpoint for faster downloads
        return `/stream/xurl?url=${encodedUrl}`

      default:
        throw new Error("Unsupported platform")
    }
  }

  // Keep original method for backward compatibility
  buildDownloadUrl(platform, url) {
    const encodedUrl = encodeURIComponent(url)

    switch (platform) {
      case "youtube":
        const type = document.getElementById("youtube-type").value
        const quality = document.getElementById("youtube-quality").value
        return `/download/${type}?song=${encodedUrl}&quality=${quality}`

      case "tiktok":
        const tiktokType = document.getElementById("tiktok-type").value
        const endpoint = tiktokType === "video" ? "tiktokurl" : "tiktoaudio"
        return `/api/${endpoint}?url=${encodedUrl}`

      case "instagram":
        return `/download/iglink?url=${encodedUrl}`

      case "facebook":
        return `/api/fburl?url=${encodedUrl}`

      case "x":
        return `/api/xurl?url=${encodedUrl}`

      default:
        throw new Error("Unsupported platform")
    }
  }
}

// Initialize the app when DOM is loaded
document.addEventListener("DOMContentLoaded", () => {
  const downloader = new MediaDownloader()

  // Make functions globally available for onclick handlers
  window.updateYouTubeQuality = () => downloader.updateYouTubeQuality()
  window.pasteFromClipboard = (inputId) => downloader.pasteFromClipboard(inputId)
  window.searchYouTube = () => downloader.searchYouTube()
  window.download = (platform) => downloader.download(platform)

  // Initialize YouTube quality options
  downloader.updateYouTubeQuality()
})
