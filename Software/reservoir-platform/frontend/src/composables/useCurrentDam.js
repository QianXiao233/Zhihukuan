import { computed, ref } from 'vue'
import { listDams } from '../api/manageApi.js'

const dams = ref([])
const selectedDamId = ref(localStorage.getItem('reservoir.currentDamId') || '')
let loadingPromise

export function useCurrentDam() {
  const currentDam = computed(() => dams.value.find((dam) => String(dam.damId) === String(selectedDamId.value)) || dams.value[0] || null)
  const currentDamName = computed(() => currentDam.value?.damName || '未选择水库')
  async function loadDams(force = false) {
    if (!force && dams.value.length) return dams.value
    if (!loadingPromise) {
      loadingPromise = listDams().then((result) => {
        dams.value = result.data || []
        if (!dams.value.some((dam) => String(dam.damId) === String(selectedDamId.value))) {
          selectedDamId.value = dams.value[0] ? String(dams.value[0].damId) : ''
          localStorage.setItem('reservoir.currentDamId', selectedDamId.value)
          window.dispatchEvent(new CustomEvent('reservoir-selection-changed', { detail: selectedDamId.value }))
        }
        return dams.value
      }).finally(() => { loadingPromise = undefined })
    }
    return loadingPromise
  }
  function selectDam(damId) {
    selectedDamId.value = damId === '' || damId === null || damId === undefined ? '' : String(damId)
    localStorage.setItem('reservoir.currentDamId', selectedDamId.value)
    window.dispatchEvent(new CustomEvent('reservoir-selection-changed', { detail: selectedDamId.value }))
  }
  return { dams, selectedDamId, currentDam, currentDamName, loadDams, selectDam }
}
