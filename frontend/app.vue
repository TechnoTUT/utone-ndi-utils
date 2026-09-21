<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'

const colorMode = useColorMode()
function toggleColorMode() {
  colorMode.preference = colorMode.value === 'dark' ? 'light' : 'dark'
}

// Types
interface NDISource {
  name: string
  stream_name: string | null
  host_name: string | null
}

interface VideoDevice {
  index: number
  name: string
  is_available: boolean
}

interface AudioDevice {
  index: number
  name: string
  max_input_channels: number
  default_samplerate: number
}

interface RxStatus {
  running: boolean
  is_connected: boolean
  current_source: string | null
  recv_fmt: string
  recv_bandwidth: string
  fullscreen: boolean
  width: number
  height: number
  fps: number
  error: string | null
}

interface TxStatus {
  running: boolean
  sender_name: string | null
  video_device: number | null
  audio_device: number | null
  no_audio: boolean
  actual_width: number
  actual_height: number
  actual_fps: number
  sample_rate: number
  audio_channels: number
  error: string | null
}

// Active Tab
const activeTab = ref<'rx' | 'tx'>('rx')

// State
const ndiSources = ref<NDISource[]>([])
const videoDevices = ref<VideoDevice[]>([])
const audioDevices = ref<AudioDevice[]>([])

const rxStatus = ref<RxStatus>({
  running: false,
  is_connected: false,
  current_source: null,
  recv_fmt: 'rgb',
  recv_bandwidth: 'highest',
  fullscreen: false,
  width: 0,
  height: 0,
  fps: 0,
  error: null
})

const txStatus = ref<TxStatus>({
  running: false,
  sender_name: null,
  video_device: null,
  audio_device: null,
  no_audio: false,
  actual_width: 0,
  actual_height: 0,
  actual_fps: 0,
  sample_rate: 0,
  audio_channels: 0,
  error: null
})

// Form Options
const rxFullscreen = ref(false)
const rxFmt = ref('rgb')
const rxBandwidth = ref('highest')

const txSenderName = ref('TX')
const txVideoDevice = ref(0)
const txAudioDevice = ref<number | null>(null)
const txNoAudio = ref(false)
const txResolution = ref('1920x1080')
const txFps = ref('30')
const txPixFmt = ref('BGRX')

// Loading states
const rxLoading = ref(false)
const txLoading = ref(false)

// API Base
const API_BASE = ''

// Fetchers
async function fetchSources() {
  try {
    const res = await fetch(`${API_BASE}/api/ndi/sources`)
    if (res.ok) {
      ndiSources.value = await res.json()
    }
  } catch (e) {
    console.error('Failed to fetch NDI sources', e)
  }
}

async function fetchDevices() {
  try {
    const [vRes, aRes] = await Promise.all([
      fetch(`${API_BASE}/api/devices/video`),
      fetch(`${API_BASE}/api/devices/audio`)
    ])
    if (vRes.ok) videoDevices.value = await vRes.json()
    if (aRes.ok) {
      const devs = await aRes.json()
      audioDevices.value = devs
      if (devs.length > 0 && txAudioDevice.value === null) {
        txAudioDevice.value = devs[0].index
      }
    }
  } catch (e) {
    console.error('Failed to fetch devices', e)
  }
}

async function fetchStatus() {
  try {
    const [rRes, tRes] = await Promise.all([
      fetch(`${API_BASE}/api/rx/status`),
      fetch(`${API_BASE}/api/tx/status`)
    ])
    if (rRes.ok) rxStatus.value = await rRes.json()
    if (tRes.ok) txStatus.value = await tRes.json()
  } catch (e) {
    console.error('Failed to fetch status', e)
  }
}

// RX Actions
async function startRx(sourceName: string) {
  rxLoading.value = true
  try {
    const res = await fetch(`${API_BASE}/api/rx/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sender_name: sourceName,
        recv_fmt: rxFmt.value,
        recv_bandwidth: rxBandwidth.value,
        fullscreen: rxFullscreen.value
      })
    })
    if (res.ok) rxStatus.value = await res.json()
  } catch (e) {
    console.error('Failed to start RX', e)
  } finally {
    rxLoading.value = false
  }
}

async function switchRx(sourceName: string) {
  rxLoading.value = true
  try {
    const res = await fetch(`${API_BASE}/api/rx/switch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sender_name: sourceName })
    })
    if (res.ok) rxStatus.value = await res.json()
  } catch (e) {
    console.error('Failed to switch RX source', e)
  } finally {
    rxLoading.value = false
  }
}

async function stopRx() {
  rxLoading.value = true
  try {
    const res = await fetch(`${API_BASE}/api/rx/stop`, { method: 'POST' })
    if (res.ok) rxStatus.value = await res.json()
  } catch (e) {
    console.error('Failed to stop RX', e)
  } finally {
    rxLoading.value = false
  }
}

// TX Actions
async function startTx() {
  txLoading.value = true
  try {
    const [x, y] = txResolution.value.split('x').map(Number)
    const res = await fetch(`${API_BASE}/api/tx/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        video_device: txVideoDevice.value,
        audio_device: txNoAudio.value ? null : txAudioDevice.value,
        no_audio: txNoAudio.value,
        sender_name: txSenderName.value,
        x_res: x,
        y_res: y,
        fps: txFps.value,
        pix_fmt: txPixFmt.value,
        sample_rate: 48000,
        audio_channels: 2
      })
    })
    if (res.ok) txStatus.value = await res.json()
  } catch (e) {
    console.error('Failed to start TX', e)
  } finally {
    txLoading.value = false
  }
}

async function stopTx() {
  txLoading.value = true
  try {
    const res = await fetch(`${API_BASE}/api/tx/stop`, { method: 'POST' })
    if (res.ok) txStatus.value = await res.json()
  } catch (e) {
    console.error('Failed to stop TX', e)
  } finally {
    txLoading.value = false
  }
}

let pollTimer: any = null

onMounted(() => {
  fetchSources()
  fetchDevices()
  fetchStatus()
  pollTimer = setInterval(() => {
    fetchSources()
    fetchStatus()
  }, 1000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div class="min-h-screen bg-slate-50 dark:bg-slate-950 text-slate-800 dark:text-slate-100 flex flex-col font-sans transition-colors duration-200">
    <!-- Top Navigation Bar -->
    <header class="border-b border-slate-200 dark:border-slate-800 bg-white/90 dark:bg-slate-900/80 backdrop-blur px-6 py-3 flex items-center justify-between sticky top-0 z-30 shadow-sm">
      <div class="flex items-center gap-5">
        <a href="/" class="flex items-center gap-4 py-0.5">
          <!-- Light theme logo (#3a3a3a + #c7000a) matching technotut.net navbar-brand (height 48px / width 200px) -->
          <img src="/logo.svg" alt="TechnoTUT" class="h-12 w-auto max-w-[200px] object-contain dark:hidden" />
          <!-- Dark theme logo (#ffffff + #c7000a) -->
          <img src="/logo_dark.svg" alt="TechnoTUT" class="h-12 w-auto max-w-[200px] object-contain hidden dark:block" />
          <div class="h-8 w-px bg-slate-200 dark:bg-slate-800"></div>
          <div>
            <h1 class="text-base font-bold tracking-tight text-slate-900 dark:text-slate-100 flex items-center gap-2">
              <span>The Utopia Tone</span>
            </h1>
            <p class="text-[11px] text-slate-500 dark:text-slate-400">MoIP Toolkit</p>
          </div>
        </a>
      </div>

      <div class="flex items-center gap-3">
        <!-- Tab Switcher -->
        <div class="flex bg-slate-100 dark:bg-slate-900 p-1 rounded-xl border border-slate-200 dark:border-slate-800">
          <button
            @click="activeTab = 'rx'"
            :class="[
              'px-5 py-2 rounded-lg text-sm font-semibold transition flex items-center gap-2',
              activeTab === 'rx' ? 'bg-[#C7000A] text-white shadow-md shadow-[#C7000A]/20' : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100'
            ]"
          >
            <span>NDI Decoder (RX)</span>
            <span
              class="h-2 w-2 rounded-full"
              :class="rxStatus.running ? (rxStatus.is_connected ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400') : 'bg-slate-300 dark:bg-slate-600'"
            />
          </button>
          <button
            @click="activeTab = 'tx'"
            :class="[
              'px-5 py-2 rounded-lg text-sm font-semibold transition flex items-center gap-2',
              activeTab === 'tx' ? 'bg-[#C7000A] text-white shadow-md shadow-[#C7000A]/20' : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100'
            ]"
          >
            <span>NDI Encoder (TX)</span>
            <span
              class="h-2 w-2 rounded-full"
              :class="txStatus.running ? 'bg-red-400 animate-pulse' : 'bg-slate-300 dark:bg-slate-600'"
            />
          </button>
        </div>

        <!-- Theme Toggle Button -->
        <button
          @click="toggleColorMode"
          class="p-2 rounded-xl border border-slate-200 dark:border-slate-800 text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800 transition"
          title="Toggle Light / Dark Mode"
        >
          <!-- Sun icon for light mode -->
          <svg v-if="colorMode.value === 'dark'" class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
          </svg>
          <!-- Moon icon for dark mode -->
          <svg v-else class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
          </svg>
        </button>
      </div>
    </header>

    <!-- Main Content -->
    <main class="flex-1 p-6 max-w-7xl mx-auto w-full space-y-6">
      
      <!-- ==================== TAB: RX (Receiver) ==================== -->
      <div v-if="activeTab === 'rx'" class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        <!-- Status & Settings Panel (Left 1 col) -->
        <div class="space-y-6 lg:col-span-1">
          <!-- Status Card -->
          <div class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-5 space-y-4 shadow-sm">
            <h2 class="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">Viewer Status</h2>
            <div class="flex items-center justify-between">
              <span class="text-slate-600 dark:text-slate-300 font-medium text-sm">Status</span>
              <span
                class="px-2.5 py-1 rounded-full text-xs font-semibold uppercase tracking-wider"
                :class="rxStatus.running ? (rxStatus.is_connected ? 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800' : 'bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400 border border-amber-200 dark:border-amber-800') : 'bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400'"
              >
                {{ rxStatus.running ? (rxStatus.is_connected ? 'Connected' : 'Searching') : 'Stopped' }}
              </span>
            </div>

            <div class="space-y-2 text-sm border-t border-slate-100 dark:border-slate-800 pt-3">
              <div class="flex justify-between">
                <span class="text-slate-500 dark:text-slate-400">Current Source:</span>
                <span class="text-slate-900 dark:text-slate-100 font-mono font-semibold truncate max-w-[180px]">{{ rxStatus.current_source || 'None' }}</span>
              </div>
              <div class="flex justify-between">
                <span class="text-slate-500 dark:text-slate-400">Resolution:</span>
                <span class="text-slate-900 dark:text-slate-100 font-mono font-medium">{{ rxStatus.width ? `${rxStatus.width} x ${rxStatus.height}` : '-' }}</span>
              </div>
            </div>

            <div v-if="rxStatus.running" class="pt-2">
              <button
                @click="stopRx"
                :disabled="rxLoading"
                class="w-full py-2.5 px-4 bg-rose-50 dark:bg-rose-950/30 hover:bg-rose-100 dark:hover:bg-rose-900/40 text-rose-700 dark:text-rose-400 border border-rose-200 dark:border-rose-800/60 rounded-xl font-medium text-sm transition"
              >
                Close Viewer Window
              </button>
            </div>
          </div>

          <!-- Launch Options -->
          <div class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-5 space-y-4 shadow-sm">
            <h2 class="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">Viewer Options</h2>
            <div class="space-y-3">
              <label class="flex items-center justify-between cursor-pointer">
                <span class="text-sm font-medium text-slate-700 dark:text-slate-300">Fullscreen Window</span>
                <input type="checkbox" v-model="rxFullscreen" class="rounded bg-white dark:bg-slate-950 border-slate-300 dark:border-slate-700 text-[#C7000A] focus:ring-[#C7000A] h-4 w-4" />
              </label>

              <div>
                <label class="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">Color Format</label>
                <select v-model="rxFmt" class="w-full bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-800 dark:text-slate-200 focus:outline-none focus:border-[#C7000A]">
                  <option value="rgb">RGB (Fast, default)</option>
                  <option value="bgr">BGR</option>
                  <option value="uyvy">UYVY (Lowest Bandwidth)</option>
                </select>
              </div>

              <div>
                <label class="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">Bandwidth Mode</label>
                <select v-model="rxBandwidth" class="w-full bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-800 dark:text-slate-200 focus:outline-none focus:border-[#C7000A]">
                  <option value="highest">Highest Quality</option>
                  <option value="lowest">Lowest Latency / Proxy</option>
                </select>
              </div>
            </div>
          </div>
        </div>

        <!-- Available Sources List (Right 2 cols) -->
        <div class="lg:col-span-2 space-y-4">
          <div class="flex items-center justify-between">
            <h2 class="text-base font-bold text-slate-900 dark:text-slate-100 tracking-tight flex items-center gap-2">
              <span>Discovered NDI Sources</span>
              <span class="text-xs bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300 font-semibold px-2 py-0.5 rounded-full">{{ ndiSources.length }}</span>
            </h2>
            <button @click="fetchSources" class="text-xs font-medium text-slate-500 dark:text-slate-400 hover:text-[#C7000A] transition">
              Refresh Sources
            </button>
          </div>

          <div v-if="ndiSources.length === 0" class="bg-white dark:bg-slate-900 border border-dashed border-slate-300 dark:border-slate-800 rounded-2xl p-12 text-center space-y-2 shadow-sm">
            <p class="text-sm font-medium text-slate-600 dark:text-slate-400">No NDI sources detected on the local network.</p>
            <p class="text-xs text-slate-400 dark:text-slate-500">Ensure NDI senders (OBS, vMix, cameras, or TX) are active on the same subnet.</p>
          </div>

          <div v-else class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div
              v-for="source in ndiSources"
              :key="source.name"
              class="bg-white dark:bg-slate-900 border rounded-2xl p-5 flex flex-col justify-between space-y-4 transition shadow-sm"
              :class="rxStatus.current_source === source.name && rxStatus.running ? 'border-[#C7000A] bg-red-50/40 dark:bg-[#C7000A]/10 ring-2 ring-[#C7000A]/30' : 'border-slate-200 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700'"
            >
              <div>
                <div class="flex items-center justify-between mb-1.5">
                  <span class="text-xs font-mono text-[#C7000A] font-bold tracking-wide uppercase">{{ source.host_name || 'Host' }}</span>
                  <span v-if="rxStatus.current_source === source.name && rxStatus.running" class="px-2 py-0.5 bg-[#C7000A] text-white text-[11px] rounded-full font-bold">Active</span>
                </div>
                <h3 class="text-base font-bold text-slate-900 dark:text-slate-100 break-all">{{ source.name }}</h3>
                <p v-if="source.stream_name" class="text-xs text-slate-500 dark:text-slate-400 mt-1">Stream: {{ source.stream_name }}</p>
              </div>

              <div>
                <button
                  v-if="rxStatus.running && rxStatus.current_source === source.name"
                  disabled
                  class="w-full py-2.5 px-3 bg-[#C7000A]/10 text-[#C7000A] border border-[#C7000A]/30 rounded-xl text-sm font-semibold"
                >
                  Currently Displaying
                </button>
                <button
                  v-else-if="rxStatus.running"
                  @click="switchRx(source.name)"
                  :disabled="rxLoading"
                  class="w-full py-2.5 px-3 bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-800 dark:text-slate-100 rounded-xl text-sm font-semibold transition"
                >
                  Switch to this Source
                </button>
                <button
                  v-else
                  @click="startRx(source.name)"
                  :disabled="rxLoading"
                  class="w-full py-2.5 px-3 bg-[#C7000A] hover:bg-[#b00009] text-white rounded-xl text-sm font-semibold transition shadow-md shadow-[#C7000A]/20"
                >
                  Open Viewer
                </button>
              </div>
            </div>
          </div>
        </div>

      </div>


      <!-- ==================== TAB: TX (Sender) ==================== -->
      <div v-if="activeTab === 'tx'" class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        <!-- Status Card (Left 1 col) -->
        <div class="space-y-6 lg:col-span-1">
          <div class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-5 space-y-4 shadow-sm">
            <h2 class="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider">Sender Status</h2>
            <div class="flex items-center justify-between">
              <span class="text-slate-600 dark:text-slate-300 font-medium text-sm">Status</span>
              <span
                class="px-2.5 py-1 rounded-full text-xs font-semibold uppercase tracking-wider"
                :class="txStatus.running ? 'bg-red-50 dark:bg-red-950/40 text-red-700 dark:text-red-400 border border-red-200 dark:border-red-800' : 'bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400'"
              >
                {{ txStatus.running ? 'Broadcasting' : 'Stopped' }}
              </span>
            </div>

            <div class="space-y-2 text-sm border-t border-slate-100 dark:border-slate-800 pt-3">
              <div class="flex justify-between">
                <span class="text-slate-500 dark:text-slate-400">Stream Name:</span>
                <span class="text-slate-900 dark:text-slate-100 font-mono font-semibold">{{ txStatus.sender_name || '-' }}</span>
              </div>
              <div class="flex justify-between">
                <span class="text-slate-500 dark:text-slate-400">Actual Output:</span>
                <span class="text-slate-900 dark:text-slate-100 font-mono font-medium">
                  {{ txStatus.actual_width ? `${txStatus.actual_width}x${txStatus.actual_height} @ ${txStatus.actual_fps.toFixed(1)}fps` : '-' }}
                </span>
              </div>
              <div class="flex justify-between">
                <span class="text-slate-500 dark:text-slate-400">Audio:</span>
                <span class="text-slate-800 dark:text-slate-200">
                  {{ txStatus.no_audio ? 'Disabled' : (txStatus.running ? `${txStatus.sample_rate}Hz (${txStatus.audio_channels}ch)` : '-') }}
                </span>
              </div>
            </div>

            <div v-if="txStatus.running" class="pt-2">
              <button
                @click="stopTx"
                :disabled="txLoading"
                class="w-full py-2.5 px-4 bg-rose-50 dark:bg-rose-950/30 hover:bg-rose-100 dark:hover:bg-rose-900/40 text-rose-700 dark:text-rose-400 border border-rose-200 dark:border-rose-800/60 rounded-xl font-medium text-sm transition"
              >
                Stop Broadcasting
              </button>
            </div>
          </div>
        </div>

        <!-- Encoder Configuration (Right 2 cols) -->
        <div class="lg:col-span-2">
          <div class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-6 space-y-6 shadow-sm">
            <h2 class="text-base font-bold text-slate-900 dark:text-slate-100 tracking-tight">NDI Encoder Configuration</h2>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <!-- NDI Stream Name -->
              <div>
                <label class="block text-xs font-bold text-slate-700 dark:text-slate-300 mb-1">NDI Stream Name</label>
                <input
                  type="text"
                  v-model="txSenderName"
                  :disabled="txStatus.running"
                  class="w-full bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:border-[#C7000A]"
                  placeholder="TX"
                />
              </div>

              <!-- Video Capture Device -->
              <div>
                <label class="block text-xs font-bold text-slate-700 dark:text-slate-300 mb-1">Camera / Video Device</label>
                <select
                  v-model="txVideoDevice"
                  :disabled="txStatus.running"
                  class="w-full bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:border-[#C7000A]"
                >
                  <option v-for="dev in videoDevices" :key="dev.index" :value="dev.index">
                    {{ dev.name }} (index {{ dev.index }})
                  </option>
                </select>
              </div>

              <!-- Target Resolution -->
              <div>
                <label class="block text-xs font-bold text-slate-700 dark:text-slate-300 mb-1">Resolution</label>
                <select
                  v-model="txResolution"
                  :disabled="txStatus.running"
                  class="w-full bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:border-[#C7000A]"
                >
                  <option value="1920x1080">1920 x 1080 (Full HD)</option>
                  <option value="1280x720">1280 x 720 (HD)</option>
                  <option value="640x480">640 x 480 (SD)</option>
                </select>
              </div>

              <!-- FPS -->
              <div>
                <label class="block text-xs font-bold text-slate-700 dark:text-slate-300 mb-1">Frame Rate (FPS)</label>
                <select
                  v-model="txFps"
                  :disabled="txStatus.running"
                  class="w-full bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:border-[#C7000A]"
                >
                  <option value="60">60 FPS</option>
                  <option value="59.94">59.94 FPS</option>
                  <option value="30">30 FPS</option>
                  <option value="29.97">29.97 FPS</option>
                  <option value="24">24 FPS</option>
                </select>
              </div>

              <!-- Pixel Format -->
              <div>
                <label class="block text-xs font-bold text-slate-700 dark:text-slate-300 mb-1">Color Format</label>
                <select
                  v-model="txPixFmt"
                  :disabled="txStatus.running"
                  class="w-full bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:border-[#C7000A]"
                >
                  <option value="BGRX">BGRX (Default)</option>
                  <option value="BGRA">BGRA</option>
                  <option value="RGBA">RGBA</option>
                </select>
              </div>

              <!-- Audio Enable -->
              <div class="flex items-end pb-2">
                <label class="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    v-model="txNoAudio"
                    :disabled="txStatus.running"
                    class="rounded bg-white dark:bg-slate-950 border-slate-300 dark:border-slate-700 text-[#C7000A] focus:ring-[#C7000A] h-4 w-4"
                  />
                  <span class="text-sm font-medium text-slate-700 dark:text-slate-300">Disable Audio (Video only)</span>
                </label>
              </div>

              <!-- Audio Device (if enabled) -->
              <div v-if="!txNoAudio" class="md:col-span-2">
                <label class="block text-xs font-bold text-slate-700 dark:text-slate-300 mb-1">Audio Input Device</label>
                <select
                  v-model="txAudioDevice"
                  :disabled="txStatus.running"
                  class="w-full bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:border-[#C7000A]"
                >
                  <option v-for="dev in audioDevices" :key="dev.index" :value="dev.index">
                    {{ dev.name }} ({{ dev.max_input_channels }}ch, {{ dev.default_samplerate }}Hz)
                  </option>
                </select>
              </div>
            </div>

            <!-- Start button -->
            <div class="pt-4 border-t border-slate-100 dark:border-slate-800">
              <button
                v-if="!txStatus.running"
                @click="startTx"
                :disabled="txLoading"
                class="w-full py-3 px-6 bg-[#C7000A] hover:bg-[#b00009] text-white rounded-xl font-bold text-sm transition shadow-md shadow-[#C7000A]/20"
              >
                Start NDI Broadcasting
              </button>
              <button
                v-else
                @click="stopTx"
                :disabled="txLoading"
                class="w-full py-3 px-6 bg-rose-600 hover:bg-rose-500 text-white rounded-xl font-bold text-sm transition shadow-md shadow-rose-600/20"
              >
                Stop Broadcasting
              </button>
            </div>

          </div>
        </div>

      </div>

    </main>
  </div>
</template>
