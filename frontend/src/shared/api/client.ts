import axios from 'axios'
import { apiBaseUrl } from '@/shared/config'
import { clearToken, getToken } from './token'

export const apiClient = axios.create({
  baseURL: apiBaseUrl,
})

apiClient.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.set('Authorization', `Bearer ${token}`)
  }
  return config
})

const LOGIN_ENDPOINT = '/api/v1/auth/login'

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const isLoginRequest = error.config?.url === LOGIN_ENDPOINT
    if (error.response?.status === 401 && !isLoginRequest) {
      clearToken()
      window.location.assign('/login')
    }
    return Promise.reject(error)
  },
)
