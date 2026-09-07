<template>
	<div>
		<div class="relative overflow-hidden rounded border bg-white">
			<!-- touch-action: none is load-bearing, not cosmetic. Without it a drag on
			     a phone scrolls the page instead of drawing, which is most of how
			     students will sign. -->
			<canvas
				ref="canvas"
				class="block w-full cursor-crosshair touch-none"
				:style="{ height: height + 'px' }"
				@pointerdown="start"
				@pointermove="draw"
				@pointerup="end"
				@pointerleave="end"
				@pointercancel="end"
			/>
			<div
				v-if="empty"
				class="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-gray-400"
			>
				{{ placeholder }}
			</div>
		</div>
		<div class="mt-1.5 flex items-center justify-between">
			<span class="text-xs text-gray-500">{{ hint }}</span>
			<button
				type="button"
				class="text-xs text-gray-600 underline disabled:text-gray-300 disabled:no-underline"
				:disabled="empty"
				@click="clear"
			>
				Clear
			</button>
		</div>
	</div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({
	modelValue: { type: String, default: '' },
	height: { type: Number, default: 150 },
	placeholder: { type: String, default: 'Sign here' },
	hint: { type: String, default: 'Sign using a finger, stylus or mouse' },
})
const emit = defineEmits(['update:modelValue'])

const canvas = ref(null)
const empty = ref(true)

let context = null
let drawing = false
let lastPoint = null

// The canvas is sized in device pixels and scaled back down, or a signature is
// a blurry mess on any screen with a pixel ratio above 1 — which is every phone.
const resize = () => {
	const element = canvas.value
	if (!element) return

	const ratio = window.devicePixelRatio || 1
	const width = element.clientWidth
	const height = props.height

	// Resizing a canvas clears it, so anything already drawn is redrawn after.
	const existing = empty.value ? null : element.toDataURL()

	element.width = width * ratio
	element.height = height * ratio

	context = element.getContext('2d')
	context.scale(ratio, ratio)
	context.lineWidth = 2
	context.lineCap = 'round'
	context.lineJoin = 'round'
	context.strokeStyle = '#1f2937'

	if (existing) {
		const image = new Image()
		image.onload = () => context.drawImage(image, 0, 0, width, height)
		image.src = existing
	}
}

const pointOf = (event) => {
	const box = canvas.value.getBoundingClientRect()
	return { x: event.clientX - box.left, y: event.clientY - box.top }
}

const start = (event) => {
	// Capture the pointer so a stroke that leaves the canvas still ends cleanly
	// rather than leaving the pad stuck in a drawing state.
	canvas.value.setPointerCapture?.(event.pointerId)
	drawing = true
	lastPoint = pointOf(event)
	// A tap with no movement is still a mark, so put a dot down immediately.
	context.beginPath()
	context.arc(lastPoint.x, lastPoint.y, context.lineWidth / 2, 0, Math.PI * 2)
	context.fill()
	empty.value = false
}

const draw = (event) => {
	if (!drawing) return
	const point = pointOf(event)
	context.beginPath()
	context.moveTo(lastPoint.x, lastPoint.y)
	context.lineTo(point.x, point.y)
	context.stroke()
	lastPoint = point
}

const end = () => {
	if (!drawing) return
	drawing = false
	lastPoint = null
	// Emitted at the end of a stroke rather than on every movement: this
	// serialises the whole canvas, which is far too much work per pointer event.
	emit('update:modelValue', canvas.value.toDataURL('image/png'))
}

const clear = () => {
	const element = canvas.value
	context.clearRect(0, 0, element.width, element.height)
	empty.value = true
	emit('update:modelValue', '')
}

onMounted(() => {
	resize()
	window.addEventListener('resize', resize)
	// A value passed in is drawn back, so the pad survives a step being revisited.
	if (props.modelValue) {
		const image = new Image()
		image.onload = () => {
			context.drawImage(image, 0, 0, canvas.value.clientWidth, props.height)
			empty.value = false
		}
		image.src = props.modelValue
	}
})

onBeforeUnmount(() => window.removeEventListener('resize', resize))
</script>
