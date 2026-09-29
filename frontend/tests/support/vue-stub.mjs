// Хук загрузчика для node:test: подменяет пакет vue минимальной заглушкой,
// чтобы проверять api.js без сборки и без установленного Vue.
export async function resolve(specifier, context, next) {
  if (specifier === 'vue') return { url: 'data:text/javascript,export const reactive = (x) => x', shortCircuit: true }
  return next(specifier, context)
}
