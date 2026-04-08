/**
 * JSON-file-based data store for MVP
 * Handles subscribers, publisher applications, and moderation queue.
 * In production, replace with PostgreSQL.
 */

import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { join, dirname } from 'node:path'

const DATA_DIR = join(process.cwd(), 'data')

async function ensureFile(filePath, defaultData) {
  try {
    const raw = await readFile(filePath, 'utf8')
    return JSON.parse(raw)
  } catch {
    await mkdir(dirname(filePath), { recursive: true })
    await writeFile(filePath, JSON.stringify(defaultData, null, 2))
    return defaultData
  }
}

// === SUBSCRIBERS ===

const SUBSCRIBERS_PATH = join(DATA_DIR, 'subscribers.json')

const DEFAULT_SUBSCRIBERS = {
  subscribers: [],
  lastUpdated: new Date().toISOString()
}

export async function getSubscribers() {
  return ensureFile(SUBSCRIBERS_PATH, DEFAULT_SUBSCRIBERS)
}

export async function addSubscriber(email, preferences = {}) {
  const data = await getSubscribers()
  const existing = data.subscribers.find(s => s.email === email)
  if (existing) {
    // Update preferences if subscriber exists
    Object.assign(existing, { preferences, updatedAt: new Date().toISOString() })
  } else {
    data.subscribers.push({
      id: `sub-${Date.now()}`,
      email,
      preferences: {
        ageGroups: preferences.ageGroups || ['3-5', '6-8'],
        topics: preferences.topics || ['nutrition', 'safety', 'development', 'play', 'wellness'],
        maxRating: preferences.maxRating || 'PG',
        ...preferences,
      },
      subscribedAt: new Date().toISOString(),
      active: true,
    })
  }
  data.lastUpdated = new Date().toISOString()
  await writeFile(SUBSCRIBERS_PATH, JSON.stringify(data, null, 2))
  return data
}

export async function updateSubscriberPreferences(email, preferences) {
  const data = await getSubscribers()
  const sub = data.subscribers.find(s => s.email === email)
  if (!sub) return null
  sub.preferences = { ...sub.preferences, ...preferences }
  sub.updatedAt = new Date().toISOString()
  data.lastUpdated = new Date().toISOString()
  await writeFile(SUBSCRIBERS_PATH, JSON.stringify(data, null, 2))
  return sub
}

export async function removeSubscriber(email) {
  const data = await getSubscribers()
  const sub = data.subscribers.find(s => s.email === email)
  if (sub) {
    sub.active = false
    sub.unsubscribedAt = new Date().toISOString()
    data.lastUpdated = new Date().toISOString()
    await writeFile(SUBSCRIBERS_PATH, JSON.stringify(data, null, 2))
  }
  return data
}

// === PUBLISHER APPLICATIONS ===

const PUBLISHERS_PATH = join(DATA_DIR, 'publishers.json')

const DEFAULT_PUBLISHERS = {
  applications: [],
  lastUpdated: new Date().toISOString()
}

export async function getPublisherApplications() {
  return ensureFile(PUBLISHERS_PATH, DEFAULT_PUBLISHERS)
}

export async function addPublisherApplication(application) {
  const data = await getPublisherApplications()
  const entry = {
    id: `pub-${Date.now()}`,
    ...application,
    status: 'pending',
    appliedAt: new Date().toISOString(),
  }
  data.applications.push(entry)
  data.lastUpdated = new Date().toISOString()
  await writeFile(PUBLISHERS_PATH, JSON.stringify(data, null, 2))
  return entry
}

export async function updatePublisherStatus(id, status, notes = '') {
  const data = await getPublisherApplications()
  const app = data.applications.find(a => a.id === id)
  if (!app) return null
  app.status = status
  app.reviewNotes = notes
  app.reviewedAt = new Date().toISOString()
  data.lastUpdated = new Date().toISOString()
  await writeFile(PUBLISHERS_PATH, JSON.stringify(data, null, 2))
  return app
}

// === MODERATION QUEUE ===

const MODERATION_PATH = join(DATA_DIR, 'moderation.json')

const DEFAULT_MODERATION = {
  queue: [],
  lastUpdated: new Date().toISOString()
}

export async function getModerationQueue() {
  return ensureFile(MODERATION_PATH, DEFAULT_MODERATION)
}

export async function addToModerationQueue(article) {
  const data = await getModerationQueue()
  data.queue.push({
    id: `mod-${Date.now()}`,
    ...article,
    status: 'pending',
    addedAt: new Date().toISOString(),
  })
  data.lastUpdated = new Date().toISOString()
  await writeFile(MODERATION_PATH, JSON.stringify(data, null, 2))
  return data
}

export async function moderateArticle(id, decision, notes = '') {
  const data = await getModerationQueue()
  const item = data.queue.find(q => q.id === id)
  if (!item) return null
  item.status = decision // 'approved', 'rejected', 'edited'
  item.moderationNotes = notes
  item.moderatedAt = new Date().toISOString()
  data.lastUpdated = new Date().toISOString()
  await writeFile(MODERATION_PATH, JSON.stringify(data, null, 2))
  return item
}

// === CUSTOM SOURCES (admin-added) ===

const CUSTOM_SOURCES_PATH = join(DATA_DIR, 'custom-sources.json')

const DEFAULT_CUSTOM_SOURCES = {
  sources: [],
  lastUpdated: new Date().toISOString()
}

export async function getCustomSources() {
  return ensureFile(CUSTOM_SOURCES_PATH, DEFAULT_CUSTOM_SOURCES)
}

export async function addCustomSource(source) {
  const data = await getCustomSources()
  data.sources.push({
    id: `src-${Date.now()}`,
    ...source,
    isActive: true,
    addedAt: new Date().toISOString(),
  })
  data.lastUpdated = new Date().toISOString()
  await writeFile(CUSTOM_SOURCES_PATH, JSON.stringify(data, null, 2))
  return data
}

export async function removeCustomSource(id) {
  const data = await getCustomSources()
  data.sources = data.sources.filter(s => s.id !== id)
  data.lastUpdated = new Date().toISOString()
  await writeFile(CUSTOM_SOURCES_PATH, JSON.stringify(data, null, 2))
  return data
}
