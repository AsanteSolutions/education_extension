import { defineStore } from 'pinia'
import { createResource } from 'frappe-ui'
import { ref, computed } from 'vue'

export const sessionStore = defineStore('education-session', () => {
  function sessionUser() {
    let cookies = new URLSearchParams(document.cookie.split('; ').join('&'))
    let _sessionUser = cookies.get('user_id')
    if (_sessionUser === 'Guest') {
      _sessionUser = null
    }
    return _sessionUser
  }

  let user = ref(sessionUser())
  const isLoggedIn = computed(() => !!user.value)

  // Signing in is Frappe's own /login page, which is where `logout` below and
  // the router's guard both send people. The resource that used to be here
  // belonged to a Vue login form with no route to reach it, and could not have
  // worked if there had been one: it called `sessionUser.reload()` on a plain
  // function, and the page that submitted it imported an export this store
  // does not have.

  const logout = createResource({
    url: 'logout',
    onSuccess() {
      user.value = null
      window.location.href = '/login'
    },
  })

  return {
    user,
    isLoggedIn,
    logout,
  }
})
