import { createRouter, createWebHistory } from 'vue-router'
import { usersStore } from '@/stores/user'
import { sessionStore } from '@/stores/session'
import { studentStore } from '@/stores/student'

const routes = [
  { path: '/', redirect: '/schedule' },
  {
    path: '/schedule',
    name: 'Schedule',
    component: () => import('@/pages/Schedule.vue'),
  },
  {
    path: '/grades',
    name: 'Grades',
    component: () => import('@/pages/Grades.vue'),
  },
  {
    path: '/fees',
    name: 'Fees',
    component: () => import('@/pages/Fees.vue'),
  },
  {
    path: '/attendance',
    name: 'Attendance',
    component: () => import('@/pages/Attendance.vue'),
  },
  {
    path: '/:catchAll(.*)',
    redirect: '/schedule',
  },
]

let router = createRouter({
  history: createWebHistory('/student-portal'),
  routes,
})

// After a deploy the built chunks get new hashed names and the old files are
// removed. A returning user with a cached index.html then requests a chunk that
// 404s, so the lazy import() rejects and the page goes blank. Recover by
// reloading once (guarded against loops) to pull the fresh index.html + chunks.
router.onError((error) => {
  const isChunkError =
    /dynamically imported module|Loading chunk|Importing a module script failed|Failed to fetch/i.test(
      error?.message || '',
    )
  if (isChunkError && !sessionStorage.getItem('chunk-reloaded')) {
    sessionStorage.setItem('chunk-reloaded', '1')
    window.location.reload()
  }
})

// Clear the reload guard once a navigation succeeds so future chunk errors can
// recover again.
router.afterEach(() => {
  sessionStorage.removeItem('chunk-reloaded')
})

router.beforeEach(async (to, from) => {
  const { isLoggedIn } = sessionStore()
  const { user } = usersStore()
  const { student } = studentStore()

  if (!isLoggedIn) {
    window.location.href = '/login'
    return false
  }

  // Don't let a failed data fetch reject the navigation — that would leave the
  // app unmounted (blank page). Let the route render and surface errors in-page.
  try {
    if (user.data.length === 0) {
      await user.reload()
    }
    await student.reload()
  } catch (e) {
    console.error('Failed to load user/student data', e)
  }
})

export default router
