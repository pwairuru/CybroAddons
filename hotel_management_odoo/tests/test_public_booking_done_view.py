from odoo.tests.common import TransactionCase


class TestPublicBookingDoneView(TransactionCase):
    def test_done_template_has_hero_card_steps(self):
        arch = self.env.ref('hotel_management_odoo.public_book_done').arch_db
        for token in ('done-hero', 'done-seal', 'done-ref', 'done-card',
                      'done-grid', 'done-steps', 'confirmation.ref',
                      'confirmation.ci', 'confirmation.co', 'confirmation.room',
                      'confirmation.state', 'wa.me/254743187486'):
            self.assertIn(token, arch)

    def test_done_gate_branch_kept(self):
        arch = self.env.ref('hotel_management_odoo.public_book_done').arch_db
        for token in ('name="ref"', 'name="last3"', 'action="/book/done"',
                      'pattern="[0-9]{3}"', 'done-gate', 't-else',
                      'couldn\'t match that reference'):
            self.assertIn(token, arch)

    def test_done_css_hooks_present(self):
        import os
        css_path = os.path.normpath(os.path.join(
            os.path.dirname(__file__), '..', 'static', 'src', 'css', 'book.css'))
        with open(css_path, encoding='utf-8') as fh:
            css = fh.read()
        for token in ('.done-hero', '.done-seal', '.done-ref', '.done-card',
                      '.done-grid', '.done-steps', '.done-gate',
                      'overflow-wrap', '@media (max-width: 43.99rem)',
                      'prefers-reduced-motion'):
            self.assertIn(token, css)
