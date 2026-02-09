#!/usr/bin/env python3
"""Creatrix — A Chaos Oracle Desktop App

PyGame desktop application for the 430-card creative oracle deck.
Two modes: DRAW (single card flip) and MUTATE (A × B → Directive).

Controls:
    Space / Click  = draw card (mode-dependent)
    M              = toggle DRAW / MUTATE
    Escape         = quit

Uses pygame._freetype directly to avoid circular import bug in
pygame 2.6.1 + Python 3.14.
"""

import sys
import random
import time
from pathlib import Path

import pygame
from pygame._freetype import init as ft_init, Font as FTFont

# Ensure imports work from any cwd
sys.path.insert(0, str(Path(__file__).parent))
from creatrix import load_strategies, load_mutants_with_traditions
from creatrix import ORIGINALS_FILE, MUTANTS_FILE
from directives import DIRECTIVES

# ── Design Tokens (Pop Chaos) ──────────────────────────────────────────

BG_VOID = (5, 5, 6)
BG_DARK = (17, 17, 20)
BG_CARD = (10, 10, 11)
RED_CORE = (255, 45, 45)
UV_VIOLET = (123, 97, 255)
TEXT_PRIMARY = (224, 224, 228)
TEXT_DIM = (85, 85, 96)
TEXT_GHOST = (51, 51, 64)
BORDER = (42, 42, 53)

# ── Constants ───────────────────────────────────────────────────────────

WIN_W, WIN_H = 900, 650
FPS = 60
CARD_W, CARD_H = 420, 280
CARD_RADIUS = 12
FLIP_DURATION = 0.3
MUTATE_STAGGER = 0.15

MENLO_PATH = "/System/Library/Fonts/Menlo.ttc"

# ── State ───────────────────────────────────────────────────────────────

MODE_DRAW = 0
MODE_MUTATE = 1

STATE_IDLE = 0
STATE_ANIMATING = 1
STATE_REVEALED = 2


class App:
    def __init__(self):
        pygame.init()
        ft_init()
        self.screen = pygame.display.set_mode((WIN_W, WIN_H), pygame.RESIZABLE)
        pygame.display.set_caption("CREATRIX")
        self.clock = pygame.time.Clock()

        self._init_fonts()

        # Load full deck once
        originals = load_strategies(ORIGINALS_FILE)
        mutants_tagged = load_mutants_with_traditions(MUTANTS_FILE)
        self.all_cards = (
            [(s, "Eno/Schmidt") for s in originals] + list(mutants_tagged)
        )
        self.deck_size = len(self.all_cards)

        # Mutate pool = all cards + directives
        self.mutate_pool = self.all_cards + DIRECTIVES

        # State
        self.mode = MODE_DRAW
        self.state = STATE_IDLE
        self.anim_start = 0.0

        # Draw mode card data
        self.current_card = None
        self.current_tradition = None

        # Mutate mode data
        self.card_a = None
        self.card_b = None
        self.directive = None

        # Animation
        self.flip_phase = 0.0
        self.mutate_phase = 0.0

    def _init_fonts(self):
        """Load Menlo via _freetype, fall back to default."""
        font_path = MENLO_PATH if Path(MENLO_PATH).exists() else None

        self.font_title = FTFont(font_path, 28)
        self.font_title.strong = True

        self.font_subtitle = FTFont(font_path, 14)
        self.font_card = FTFont(font_path, 20)
        self.font_tradition = FTFont(font_path, 13)
        self.font_hint = FTFont(font_path, 13)

        self.font_mutate_label = FTFont(font_path, 16)
        self.font_mutate_label.strong = True

        self.font_mutate_card = FTFont(font_path, 18)

        self.font_directive = FTFont(font_path, 18)
        self.font_directive.strong = True

    # ── Helpers for _freetype API ───────────────────────────────────────

    def _render_text(self, font, text, color):
        """Render text, return surface. Wraps _freetype (surf, rect) API."""
        surf, _ = font.render(text, fgcolor=color)
        return surf

    def _text_width(self, font, text):
        """Get pixel width of text string."""
        return font.get_rect(text).width

    def _line_height(self, font):
        """Get line height for a font."""
        return int(font.get_sized_height())

    # ── Card picking ────────────────────────────────────────────────────

    def _pick_card(self):
        card, tradition = random.choice(self.all_cards)
        self.current_card = card
        self.current_tradition = tradition

    def _pick_mutate(self):
        picks = random.sample(self.mutate_pool, 3)
        self.card_a = {"card": picks[0][0], "tradition": picks[0][1]}
        self.card_b = {"card": picks[1][0], "tradition": picks[1][1]}
        self.directive = {"card": picks[2][0], "tradition": picks[2][1]}

    # ── Input handling ──────────────────────────────────────────────────

    def handle_draw_action(self):
        if self.state == STATE_ANIMATING:
            return
        if self.mode == MODE_DRAW:
            self._pick_card()
            self.state = STATE_ANIMATING
            self.anim_start = time.time()
            self.flip_phase = 0.0
        else:
            self._pick_mutate()
            self.state = STATE_ANIMATING
            self.anim_start = time.time()
            self.mutate_phase = 0.0

    def toggle_mode(self):
        if self.state == STATE_ANIMATING:
            return
        self.mode = MODE_MUTATE if self.mode == MODE_DRAW else MODE_DRAW
        self.state = STATE_IDLE
        self.current_card = None
        self.card_a = None

    # ── Update ──────────────────────────────────────────────────────────

    def update(self):
        if self.state != STATE_ANIMATING:
            return
        elapsed = time.time() - self.anim_start

        if self.mode == MODE_DRAW:
            self.flip_phase = min(elapsed / FLIP_DURATION, 1.0)
            if self.flip_phase >= 1.0:
                self.state = STATE_REVEALED
        else:
            total = 5 * MUTATE_STAGGER
            self.mutate_phase = min(elapsed / total, 1.0)
            if self.mutate_phase >= 1.0:
                self.state = STATE_REVEALED

    # ── Render ──────────────────────────────────────────────────────────

    def render(self):
        w, h = self.screen.get_size()
        self.screen.fill(BG_VOID)

        self._render_header(w)
        self._render_hints(w, h)

        if self.mode == MODE_DRAW:
            self._render_draw_mode(w, h)
        else:
            self._render_mutate_mode(w, h)

        pygame.display.flip()

    def _render_header(self, w):
        title_surf = self._render_text(self.font_title, "C R E A T R I X", TEXT_PRIMARY)
        self.screen.blit(title_surf, (w // 2 - title_surf.get_width() // 2, 28))

        if self.mode == MODE_DRAW:
            sub, sub_color = "a chaos oracle by pop chaos", TEXT_DIM
        else:
            sub, sub_color = "M U T A T E", UV_VIOLET
        sub_surf = self._render_text(self.font_subtitle, sub, sub_color)
        self.screen.blit(sub_surf, (w // 2 - sub_surf.get_width() // 2, 62))

    def _render_hints(self, w, h):
        action = "draw" if self.mode == MODE_DRAW else "mutate"
        toggle = "mutate" if self.mode == MODE_DRAW else "draw"
        hint = f"[ SPACE ] {action}  |  [ M ] {toggle}  |  {self.deck_size}"
        hint_surf = self._render_text(self.font_hint, hint, TEXT_GHOST)
        self.screen.blit(hint_surf, (w // 2 - hint_surf.get_width() // 2, h - 38))

    # ── DRAW MODE ───────────────────────────────────────────────────────

    def _render_draw_mode(self, w, h):
        cx, cy = w // 2, h // 2 + 10

        if self.state == STATE_IDLE:
            self._draw_card_rect(cx, cy, False, 1.0)
        elif self.state == STATE_ANIMATING:
            if self.flip_phase < 0.5:
                sx = 1.0 - (self.flip_phase / 0.5)
                self._draw_card_rect(cx, cy, False, max(sx, 0.02))
            else:
                sx = (self.flip_phase - 0.5) / 0.5
                self._draw_card_rect(cx, cy, True, max(sx, 0.02))
        elif self.state == STATE_REVEALED:
            self._draw_card_rect(cx, cy, True, 1.0)

    def _draw_card_rect(self, cx, cy, face_up, scale_x):
        cw = int(CARD_W * scale_x)
        ch = CARD_H
        if cw < 2:
            return

        rect = pygame.Rect(cx - cw // 2, cy - ch // 2, cw, ch)
        pygame.draw.rect(self.screen, BG_CARD, rect, border_radius=CARD_RADIUS)
        border_color = RED_CORE if face_up else BORDER
        pygame.draw.rect(self.screen, border_color, rect, width=2,
                         border_radius=CARD_RADIUS)

        if not face_up:
            diamond = self._render_text(self.font_card, "◆", TEXT_GHOST)
            self.screen.blit(diamond, (cx - diamond.get_width() // 2,
                                        cy - diamond.get_height() // 2))
        elif self.current_card:
            self._draw_wrapped_center(
                self.current_card, self.font_card, TEXT_PRIMARY,
                cx, cy - 20, cw - 40
            )
            if self.current_tradition:
                div_y = cy + ch // 2 - 50
                pygame.draw.line(self.screen, BORDER,
                                 (cx - cw // 3, div_y), (cx + cw // 3, div_y))
                trad_surf = self._render_text(
                    self.font_tradition, self.current_tradition.upper(), TEXT_DIM
                )
                self.screen.blit(trad_surf,
                                 (cx - trad_surf.get_width() // 2, div_y + 10))

    # ── MUTATE MODE ─────────────────────────────────────────────────────

    def _render_mutate_mode(self, w, h):
        if self.state == STATE_IDLE:
            surf = self._render_text(self.font_card, "Press SPACE to mutate", TEXT_GHOST)
            self.screen.blit(surf, (w // 2 - surf.get_width() // 2, h // 2))
            return
        if not self.card_a:
            return

        def elem_alpha(index):
            if self.state == STATE_REVEALED:
                return 1.0
            slot = index / 5.0
            slot_end = (index + 1) / 5.0
            if self.mutate_phase < slot:
                return 0.0
            if self.mutate_phase >= slot_end:
                return 1.0
            return (self.mutate_phase - slot) / (slot_end - slot)

        lm = max(60, w // 8)
        cw = w - 2 * lm
        y = 110

        # Card A
        a = elem_alpha(0)
        if a > 0:
            y = self._render_mutate_card("A", self.card_a, lm, y, cw, a)
        y += 20

        # × symbol
        xa = elem_alpha(1)
        if xa > 0:
            sym = self._render_text(self.font_mutate_label, "×",
                                     self._fade(TEXT_DIM, xa))
            self.screen.blit(sym, (lm + 22, y))
        y += 30

        # Card B
        ba = elem_alpha(2)
        if ba > 0:
            y = self._render_mutate_card("B", self.card_b, lm, y, cw, ba)
        y += 25

        # Separator
        sa = elem_alpha(3)
        if sa > 0:
            pygame.draw.line(self.screen, self._fade(BORDER, sa),
                             (lm, y), (w - lm, y), 2)
        y += 20

        # Directive (HOW)
        da = elem_alpha(4)
        if da > 0:
            label = self._render_text(self.font_mutate_label, "HOW:",
                                       self._fade(UV_VIOLET, da))
            self.screen.blit(label, (lm, y))
            y += 28

            self._draw_wrapped_left(
                self.directive["card"], self.font_directive,
                self._fade(UV_VIOLET, da), lm + 10, y, cw - 10
            )
            lines = self._count_lines(self.directive["card"],
                                       self.font_directive, cw - 10)
            y += lines * self._line_height(self.font_directive) + 8

            trad = self.directive["tradition"].upper()
            trad_surf = self._render_text(self.font_tradition, trad,
                                           self._fade(TEXT_GHOST, da))
            self.screen.blit(trad_surf, (lm + 10, y))

    def _render_mutate_card(self, label, card_data, x, y, max_w, alpha):
        lbl = self._render_text(self.font_mutate_label, f"{label} ---",
                                 self._fade(RED_CORE, alpha))
        self.screen.blit(lbl, (x, y))
        y += 26

        text = f'"{card_data["card"]}"'
        self._draw_wrapped_left(text, self.font_mutate_card,
                                 self._fade(TEXT_PRIMARY, alpha),
                                 x + 30, y, max_w - 30)
        lines = self._count_lines(text, self.font_mutate_card, max_w - 30)
        y += lines * self._line_height(self.font_mutate_card) + 4

        trad = card_data["tradition"].upper()
        trad_surf = self._render_text(self.font_tradition, f"[{trad}]",
                                       self._fade(TEXT_GHOST, alpha))
        self.screen.blit(trad_surf, (x + 30, y))
        y += 22
        return y

    # ── Text layout helpers ─────────────────────────────────────────────

    def _wrap_lines(self, text, font, max_w):
        words = text.split()
        lines = []
        cur = ""
        for word in words:
            test = cur + (" " if cur else "") + word
            if self._text_width(font, test) <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines

    def _draw_wrapped_center(self, text, font, color, cx, cy, max_w):
        lines = self._wrap_lines(text, font, max_w)
        lh = self._line_height(font)
        start_y = cy - (lh * len(lines)) // 2
        for i, line in enumerate(lines):
            surf = self._render_text(font, line, color)
            self.screen.blit(surf, (cx - surf.get_width() // 2, start_y + i * lh))

    def _draw_wrapped_left(self, text, font, color, x, y, max_w):
        lines = self._wrap_lines(text, font, max_w)
        lh = self._line_height(font)
        for i, line in enumerate(lines):
            surf = self._render_text(font, line, color)
            self.screen.blit(surf, (x, y + i * lh))

    def _count_lines(self, text, font, max_w):
        return len(self._wrap_lines(text, font, max_w))

    def _fade(self, color, alpha):
        return (
            int(BG_VOID[0] + (color[0] - BG_VOID[0]) * alpha),
            int(BG_VOID[1] + (color[1] - BG_VOID[1]) * alpha),
            int(BG_VOID[2] + (color[2] - BG_VOID[2]) * alpha),
        )

    # ── Main loop ───────────────────────────────────────────────────────

    def run(self):
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_SPACE:
                        self.handle_draw_action()
                    elif event.key == pygame.K_m:
                        self.toggle_mode()
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1:
                        self.handle_draw_action()

            self.update()
            self.render()
            self.clock.tick(FPS)

        pygame.quit()


if __name__ == "__main__":
    app = App()
    app.run()
