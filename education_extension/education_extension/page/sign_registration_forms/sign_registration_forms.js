// Copyright (c) 2026, Asante Solutions and contributors
// For license information, please see license.txt

/* The registrar's countersigning queue.
 *
 * A student signs their consent on the portal and the Proof of Registration
 * prints it; the registrar's line was the one still being signed on paper. This
 * is that job done once through: the forms still to sign down the left, the one
 * in hand on the right with the modules it covers, and a button.
 *
 * The controls are built into the page body rather than added to the page's own
 * filter bar. That bar is easy to miss and turned out to be — the first version
 * put "Still to sign / Signed / All" there and it read as though there were no
 * way to see a form once it had been signed. Here they are three buttons
 * carrying their own counts, which also answers "how many are left" without
 * anyone having to ask.
 *
 * The list is deliberately light — names and dates only. Each drawn signature
 * is tens of kilobytes, and a term is a couple of hundred forms, so the one on
 * screen is fetched on its own.
 */

frappe.pages['sign-registration-forms'].on_page_load = (wrapper) => {
	new SigningQueue(wrapper);
};

const API = 'education_extension.education_extension.registration_forms.';

const STATES = [
	{ value: 'unsigned', label: __('Still to sign') },
	{ value: 'signed', label: __('Signed') },
	{ value: 'all', label: __('All') },
];

class SigningQueue {
	constructor(wrapper) {
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __('Sign Registration Forms'),
			single_column: true,
		});
		this.rows = [];
		this.counts = {};
		this.selected = null;
		this.state = 'unsigned';
		this.term = null;

		this.make_layout();
		this.make_controls();
		this.page.set_primary_action(__('Sign All Remaining'), () => this.sign_all());
		this.refresh();
	}

	make_layout() {
		this.page.main.html(`
			<div class="ee-toolbar">
				<div class="ee-term"></div>
				<div class="ee-states btn-group"></div>
			</div>
			<div class="ee-signing">
				<div class="ee-queue">
					<div class="ee-queue-head"></div>
					<div class="ee-queue-list"></div>
				</div>
				<div class="ee-form"></div>
			</div>
		`);
		this.$toolbar = this.page.main.find('.ee-toolbar');
		this.$states = this.page.main.find('.ee-states');
		this.$list = this.page.main.find('.ee-queue-list');
		this.$head = this.page.main.find('.ee-queue-head');
		this.$form = this.page.main.find('.ee-form');

		frappe.dom.set_style(`
			.ee-toolbar { display: flex; gap: 16px; align-items: flex-end;
				margin-bottom: 12px; flex-wrap: wrap; }
			.ee-term { min-width: 260px; }
			.ee-signing { display: flex; gap: 16px; align-items: flex-start; }
			.ee-queue { flex: 0 0 280px; border: 1px solid var(--border-color);
				border-radius: var(--border-radius-md); overflow: hidden; }
			.ee-queue-head { padding: 8px 12px; font-weight: 600;
				border-bottom: 1px solid var(--border-color); background: var(--fg-color); }
			.ee-queue-list { max-height: 70vh; overflow-y: auto; }
			.ee-queue-row { padding: 8px 12px; cursor: pointer;
				border-bottom: 1px solid var(--border-color); }
			.ee-queue-row:hover { background: var(--bg-color); }
			.ee-queue-row.is-selected { background: var(--bg-light-gray); font-weight: 600; }
			.ee-queue-row .ee-id { color: var(--text-muted); font-size: var(--text-sm); }
			.ee-form { flex: 1 1 auto; border: 1px solid var(--border-color);
				border-radius: var(--border-radius-md); padding: 16px; min-height: 320px; }
			.ee-modules { width: 100%; border-collapse: collapse; margin: 8px 0 16px; }
			.ee-modules th, .ee-modules td { text-align: left; padding: 4px 8px;
				border-bottom: 1px solid var(--border-color); font-size: var(--text-sm); }
			.ee-signature { border: 1px solid var(--border-color); border-radius: 4px;
				max-height: 90px; background: #fff; padding: 4px; }
			.ee-muted { color: var(--text-muted); }
			.ee-provisional { color: var(--orange-600); }
		`);
	}

	make_controls() {
		this.term_field = frappe.ui.form.make_control({
			parent: this.$toolbar.find('.ee-term'),
			df: {
				fieldname: 'academic_term',
				label: __('Academic Term'),
				fieldtype: 'Link',
				options: 'Academic Term',
				change: () => {
					this.term = this.term_field.get_value() || null;
					this.refresh();
				},
			},
			render_input: true,
		});

		this.render_states();

		// Open on the term being registered, the same one the reports default to.
		frappe.db
			.get_list('Registration Period', {
				fields: ['academic_term'],
				order_by: 'opens_on desc',
				limit: 1,
			})
			.then((periods) => {
				if (periods && periods.length) {
					this.term_field.set_value(periods[0].academic_term);
				}
			});
	}

	render_states() {
		this.$states.empty();
		STATES.forEach((state) => {
			const count = this.counts[state.value];
			const label = count === undefined ? state.label : `${state.label} (${count})`;
			$(
				`<button class="btn btn-sm ${
					this.state === state.value ? 'btn-primary' : 'btn-default'
				}">${label}</button>`
			)
				.appendTo(this.$states)
				.on('click', () => {
					this.state = state.value;
					this.render_states();
					this.refresh();
				});
		});
	}

	refresh() {
		// Every state, so the buttons can carry counts and the reader can see
		// at a glance that signed forms have not gone anywhere.
		frappe
			.call({ method: API + 'forms', args: { academic_term: this.term, state: 'all' } })
			.then((r) => {
				const all = r.message || [];
				this.counts = {
					unsigned: all.filter((row) => !row.signed).length,
					signed: all.filter((row) => row.signed).length,
					all: all.length,
				};
				this.rows =
					this.state === 'all' ? all : all.filter((row) => row.signed === (this.state === 'signed'));

				this.render_states();
				this.render_list();

				const still = this.rows.find((row) => row.name === this.selected);
				this.select(still ? still.name : (this.rows[0] || {}).name);
			});
	}

	render_list() {
		const state = STATES.find((s) => s.value === this.state);
		this.$head.text(`${state.label} (${this.rows.length})`);

		if (!this.rows.length) {
			this.$list.html(`<div class="ee-queue-row ee-muted">${__('Nothing here.')}</div>`);
			return;
		}

		this.$list.html(
			this.rows
				.map(
					(row) => `
					<div class="ee-queue-row" data-name="${frappe.utils.escape_html(row.name)}">
						<div>${frappe.utils.escape_html(row.student_name || row.student)}</div>
						<div class="ee-id">${frappe.utils.escape_html(row.student)}${
							row.signed ? ' &middot; ' + __('signed') : ''
						}</div>
					</div>`
				)
				.join('')
		);

		this.$list.find('.ee-queue-row').on('click', (event) => {
			this.select($(event.currentTarget).attr('data-name'));
		});
	}

	select(name) {
		this.selected = name;
		this.$list.find('.ee-queue-row').removeClass('is-selected');
		if (!name) {
			this.$form.html(`<div class="ee-muted">${__('Select a form.')}</div>`);
			return;
		}
		this.$list.find(`[data-name="${name}"]`).addClass('is-selected');

		frappe.call({ method: API + 'form', args: { consent: name } }).then((r) => {
			if (this.selected === name) this.render_form(r.message);
		});
	}

	render_form(form) {
		if (!form) return;

		const modules = form.modules.length
			? `<table class="ee-modules">
					<tr><th>${__('Module')}</th><th>${__('Name')}</th><th>${__('Programme')}</th></tr>
					${form.modules
						.map(
							(row) => `<tr>
								<td>${frappe.utils.escape_html(row.course.split(' - ')[0])}</td>
								<td>${frappe.utils.escape_html(row.course_name || '')}${
									row.provisional
										? ` <span class="ee-provisional">(${__('provisional')})</span>`
										: ''
								}</td>
								<td>${frappe.utils.escape_html(row.program || '')}</td>
							</tr>`
						)
						.join('')}
				</table>`
			: `<p class="ee-muted">${__(
					'No modules are registered against this consent. Worth looking at before signing.'
			  )}</p>`;

		const signature = (mark, label) =>
			mark
				? `<div><img src="${mark}" class="ee-signature" /><div class="ee-id">${label}</div></div>`
				: `<div class="ee-muted">${label}: ${__('not signed')}</div>`;

		this.$form.html(`
			<h4>${frappe.utils.escape_html(form.student_name || form.student)}
				<span class="ee-id">${frappe.utils.escape_html(form.student)}</span></h4>
			<div class="ee-id">${frappe.utils.escape_html(form.academic_term || '')} &middot;
				${__('consented')} ${frappe.datetime.str_to_user(form.consented_at) || ''}</div>

			<h5 style="margin-top:16px">${__('Modules')} (${form.modules.length})</h5>
			${modules}

			<h5>${__('Signatures')}</h5>
			<div style="display:flex; gap:24px; flex-wrap:wrap; margin-bottom:16px">
				${signature(form.student_signature, __('Student'))}
				${
					form.signed_by_guardian
						? signature(
								form.guardian_signature,
								frappe.utils.escape_html(form.guardian_name || __('Guardian'))
						  )
						: ''
				}
				${signature(form.registrar_signature, __('Registrar'))}
			</div>

			<div class="ee-actions"></div>
		`);

		const $actions = this.$form.find('.ee-actions');
		if (form.signed) {
			$(
				`<div class="ee-muted">${__('Signed by {0} on {1}.', [
					frappe.utils.escape_html(form.registrar_name || ''),
					frappe.datetime.str_to_user(form.registrar_signed_at),
				])}</div>`
			).appendTo($actions);
			$(
				`<button class="btn btn-default btn-sm" style="margin-top:8px">${__(
					'Remove Signature'
				)}</button>`
			)
				.appendTo($actions)
				.on('click', () => this.unsign(form.name));
		} else {
			$(`<button class="btn btn-primary btn-sm">${__('Sign')}</button>`)
				.appendTo($actions)
				.on('click', () => this.sign(form.name));
			$(`<button class="btn btn-default btn-sm" style="margin-left:8px">${__('Skip')}</button>`)
				.appendTo($actions)
				.on('click', () => this.advance());
		}
	}

	/* Where to go after signing: the next one down, so a queue can be worked
	 * through without going back to the list each time. */
	advance() {
		const at = this.rows.findIndex((row) => row.name === this.selected);
		const next = this.rows[at + 1] || this.rows[at - 1];
		this.select(next ? next.name : null);
	}

	sign(name) {
		frappe.call({ method: API + 'sign', args: { consent: name } }).then(() => {
			frappe.show_alert({ message: __('Signed'), indicator: 'green' });
			const after = this.rows[this.rows.findIndex((row) => row.name === name) + 1];
			this.selected = after ? after.name : null;
			this.refresh();
		});
	}

	unsign(name) {
		frappe.confirm(__('Take the registrar signature off this form?'), () => {
			frappe.call({ method: API + 'unsign', args: { consent: name } }).then(() => {
				frappe.show_alert({ message: __('Signature removed'), indicator: 'orange' });
				this.refresh();
			});
		});
	}

	sign_all() {
		const waiting = this.counts.unsigned || 0;
		if (!waiting) {
			frappe.msgprint(__('There is nothing left to sign here.'));
			return;
		}

		frappe.confirm(__('Sign all {0} remaining forms?', [waiting]), () => {
			frappe.call({
				method: API + 'sign_all',
				args: { academic_term: this.term },
				freeze: true,
				freeze_message: __('Signing {0} forms...', [waiting]),
				callback: (r) => {
					const out = r.message || { signed: [], problems: [] };
					frappe.show_alert({
						message: __('{0} signed', [out.signed.length]),
						indicator: 'green',
					});
					if (out.problems.length) {
						frappe.msgprint({
							title: __('Some forms were not signed'),
							indicator: 'orange',
							message: out.problems
								.map(
									(p) =>
										`${frappe.utils.escape_html(p.consent)}: ${frappe.utils.escape_html(
											p.reason
										)}`
								)
								.join('<br>'),
						});
					}
					this.refresh();
				},
			});
		});
	}
}
