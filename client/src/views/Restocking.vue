<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div class="card budget-card">
      <div class="card-header">
        <h3 class="card-title">{{ t('restocking.budgetLabel') }}</h3>
      </div>
      <div class="budget-controls">
        <input
          type="range"
          min="0"
          max="20000"
          step="500"
          v-model.number="budget"
          class="budget-slider"
        />
        <span class="budget-readout">{{ currencySymbol }}{{ budget.toLocaleString() }}</span>
      </div>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="loadError" class="error">{{ loadError }}</div>
    <div v-else>
      <div v-if="orderSuccess" class="success-banner">
        {{ t('restocking.orderPlacedMessage', { orderNumber: orderSuccess.order_number, days: orderSuccess.lead_time_days }) }}
      </div>
      <div v-if="orderError" class="error">{{ orderError }}</div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.totalCost') }}</h3>
        </div>
        <div class="summary-content">
          <div class="summary-row">
            <span>{{ currencySymbol }}{{ recommendations?.total_cost?.toLocaleString() ?? 0 }} / {{ currencySymbol }}{{ budget.toLocaleString() }}</span>
            <span class="remaining-budget">
              {{ t('restocking.remainingBudget') }}: {{ currencySymbol }}{{ recommendations?.remaining_budget?.toLocaleString() ?? 0 }}
            </span>
          </div>
          <div class="budget-progress-bar">
            <div
              class="budget-progress"
              :class="{ over: budgetUsagePercent >= 100 }"
              :style="{ width: Math.min(budgetUsagePercent, 100) + '%' }"
            ></div>
          </div>
        </div>
      </div>

      <div v-if="!recommendations || recommendations.recommended_items.length === 0" class="card">
        <p class="no-recommendations">{{ t('restocking.noRecommendations') }}</p>
      </div>

      <template v-else>
        <div class="card">
          <div class="card-header">
            <h3 class="card-title">{{ t('restocking.recommendedItems') }} ({{ recommendations.recommended_items.length }})</h3>
          </div>
          <div class="table-container">
            <table>
              <thead>
                <tr>
                  <th>{{ t('restocking.table.sku') }}</th>
                  <th>{{ t('restocking.table.itemName') }}</th>
                  <th>{{ t('restocking.table.trend') }}</th>
                  <th>{{ t('restocking.table.quantity') }}</th>
                  <th>{{ t('restocking.table.unitCost') }}</th>
                  <th>{{ t('restocking.table.lineCost') }}</th>
                  <th>{{ t('restocking.table.status') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="item in recommendations.recommended_items"
                  :key="item.item_sku"
                  :class="{ 'dimmed-row': !item.included }"
                >
                  <td><strong>{{ item.item_sku }}</strong></td>
                  <td>{{ translateProductName(item.item_name) }}</td>
                  <td>
                    <span :class="['badge', item.trend]">{{ t(`trends.${item.trend}`) }}</span>
                  </td>
                  <td>{{ item.recommended_quantity }}</td>
                  <td>{{ currencySymbol }}{{ item.unit_cost.toLocaleString() }}</td>
                  <td>{{ currencySymbol }}{{ item.line_cost.toLocaleString() }}</td>
                  <td>
                    <span :class="['badge', item.included ? 'success' : 'warning']">
                      {{ item.included ? t('restocking.included') : t('restocking.excluded') }}
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-if="recommendations.excluded_items.length > 0" class="excluded-note">
            <p>{{ t('restocking.excludedNote', { count: recommendations.excluded_items.length }) }}</p>
            <p class="excluded-list">
              {{ recommendations.excluded_items.map(i => translateProductName(i.item_name)).join(', ') }}
            </p>
          </div>
        </div>

        <div class="place-order-container">
          <button
            class="place-order-btn"
            :disabled="loading || placingOrder || includedCount === 0"
            @click="placeOrder"
          >
            {{ placingOrder ? t('restocking.placingOrder') : t('restocking.placeOrder') }}
          </button>
        </div>
      </template>
    </div>
  </div>
</template>

<script>
import { ref, computed, watch, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency, translateProductName } = useI18n()

    const currencySymbol = computed(() => {
      return currentCurrency.value === 'JPY' ? '¥' : '$'
    })

    const budget = ref(5000)
    const loading = ref(false)
    const loadError = ref(null)
    const recommendations = ref(null)

    const placingOrder = ref(false)
    const orderError = ref(null)
    const orderSuccess = ref(null)

    let debounceTimer = null

    const loadRecommendations = async () => {
      loading.value = true
      loadError.value = null
      try {
        recommendations.value = await api.getRestockingRecommendations(budget.value)
      } catch (err) {
        loadError.value = 'Failed to load restocking recommendations: ' + err.message
      } finally {
        loading.value = false
      }
    }

    watch(budget, () => {
      if (debounceTimer) clearTimeout(debounceTimer)
      debounceTimer = setTimeout(() => {
        loadRecommendations()
      }, 300)
    })

    const includedCount = computed(() => {
      if (!recommendations.value) return 0
      return recommendations.value.recommended_items.filter(i => i.included).length
    })

    const budgetUsagePercent = computed(() => {
      if (!recommendations.value || !budget.value) return 0
      return (recommendations.value.total_cost / budget.value) * 100
    })

    const placeOrder = async () => {
      if (!recommendations.value) return
      placingOrder.value = true
      orderError.value = null
      try {
        const skus = recommendations.value.recommended_items
          .filter(i => i.included)
          .map(i => i.item_sku)
        const order = await api.createRestockingOrder(budget.value, skus)
        orderSuccess.value = order
      } catch (err) {
        orderError.value = 'Failed to place restocking order: ' + err.message
      } finally {
        placingOrder.value = false
      }
    }

    onMounted(loadRecommendations)

    return {
      t,
      currencySymbol,
      budget,
      loading,
      loadError,
      recommendations,
      placingOrder,
      orderError,
      orderSuccess,
      includedCount,
      budgetUsagePercent,
      placeOrder,
      translateProductName
    }
  }
}
</script>

<style scoped>
.budget-card {
  margin-bottom: 1.25rem;
}

.budget-controls {
  display: flex;
  align-items: center;
  gap: 1.25rem;
}

.budget-slider {
  flex: 1;
  accent-color: #3b82f6;
}

.budget-readout {
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
  min-width: 100px;
  text-align: right;
}

.summary-content {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.summary-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.938rem;
  color: #334155;
}

.remaining-budget {
  color: #64748b;
  font-size: 0.875rem;
}

.budget-progress-bar {
  width: 100%;
  height: 8px;
  background: #f1f5f9;
  border-radius: 4px;
  overflow: hidden;
}

.budget-progress {
  height: 100%;
  background: #3b82f6;
  border-radius: 4px;
  transition: width 0.6s ease;
}

.budget-progress.over {
  background: #ef4444;
}

.dimmed-row {
  opacity: 0.55;
}

.excluded-note {
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid #f1f5f9;
  font-size: 0.875rem;
  color: #64748b;
}

.excluded-list {
  margin-top: 0.375rem;
  color: #94a3b8;
}

.no-recommendations {
  text-align: center;
  padding: 2rem;
  color: #64748b;
}

.place-order-container {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 1.25rem;
}

.place-order-btn {
  padding: 0.75rem 1.5rem;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  font-size: 0.938rem;
  cursor: pointer;
  transition: all 0.2s ease;
}

.place-order-btn:hover:not(:disabled) {
  background: #2563eb;
  transform: translateY(-1px);
  box-shadow: 0 2px 4px rgba(59, 130, 246, 0.3);
}

.place-order-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.success-banner {
  background: #d1fae5;
  border: 1px solid #6ee7b7;
  color: #065f46;
  padding: 1rem;
  border-radius: 8px;
  margin: 1rem 0;
  font-size: 0.938rem;
  font-weight: 600;
}
</style>
