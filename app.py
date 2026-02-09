#!/usr/bin/env python3
"""Creatrix — A Chaos Oracle Desktop App (Terminal-as-Interface Edition)

PyGame desktop application for the 430-card creative oracle deck.
Renders as a terminal emulator: monospace text, box-drawing frames,
yellowish-green on charcoal. The terminal IS the design.

Two modes: DRAW (single card with ritual pacing) and MUTATE (A × B → Directive).

Controls:
    Space / Click  = draw card / flip back (mode-dependent)
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

# ── Terminal Palette (Pop Chaos Design System) ───────────────────────────
# The terminal IS the design. Yellowish-green on charcoal.

BG        = (30, 30, 30)       # Charcoal background
BG_DARK   = (22, 22, 22)       # Deeper charcoal
BG_CARD   = (36, 36, 36)       # Card/panel interior
TEXT      = (184, 224, 110)    # Yellowish-green primary
TEXT_BRT  = (212, 255, 127)    # Bright emphasis
TEXT_DIM  = (122, 156, 58)     # De-emphasized
TEXT_GHOST = (61, 80, 32)      # Barely visible
UV_VIOLET = (123, 97, 255)    # Special accent
RED_CORE  = (255, 45, 45)     # Danger/emphasis
BORDER    = (58, 80, 32)      # Green-tinted border

# ── Constants ────────────────────────────────────────────────────────────

WIN_W, WIN_H = 720, 560
FPS = 60
FADE_DURATION = 0.4            # Seconds to fade in card text
STAGGER_DELAY = 0.12           # Seconds between mutate lines
ABSORB_DURATION = 3.0          # Seconds before card auto-flips back

MENLO_PATH = "/System/Library/Fonts/Menlo.ttc"
CHAR_W_APPROX = 10            # Approximate monospace character width at size 16

# ── Box Drawing ──────────────────────────────────────────────────────────

BOX_TL = "╔"
BOX_TR = "╗"
BOX_BL = "╚"
BOX_BR = "╝"
BOX_H  = "═"
BOX_V  = "║"
BOX_T_DOWN = "╦"
BOX_T_UP   = "╩"
BOX_T_RIGHT = "╠"
BOX_T_LEFT  = "╣"

# ── State Machine ────────────────────────────────────────────────────────

MODE_DRAW = 0
MODE_MUTATE = 1

STATE_IDLE = 0          # Card face-down, waiting for input
STATE_REVEALING = 1     # Fading in card text
STATE_REVEALED = 2      # Card visible, absorb timer running
STATE_HIDING = 3        # Fading out card text back to face-down


class App:
    def __init__(self):
        pygame.init()
        ft_init()
        self.screen = pygame.display.set_mode((WIN_W, WIN_H), pygame.RESIZABLE)
        pygame.display.set_caption("CREATRIX")
        self.clock = pygame.time.Clock()

        self._init_fonts()

        # Load full deck
        originals = load_strategies(ORIGINALS_FILE)
        mutants_tagged = load_mutants_with_traditions(MUTANTS_FILE)
        self.all_cards = (
            [(s, "Eno/Schmidt") for s in originals] + list(mutants_tagged)
        )
        self.deck_size = len(self.all_cards)
        self.mutate_pool = self.all_cards + DIRECTIVES

        # State
        self.mode = MODE_DRAW
        self.state = STATE_IDLE
        self.anim_start = 0.0
        self.reveal_time = 0.0       # When card was fully revealed

        # Draw mode
        self.current_card = None
        self.current_tradition = None

        # Mutate mode
        self.card_a = None
        self.card_b = None
        self.directive = None

        # Animation
        self.fade_alpha = 0.0
        self.mutate_line_alphas = [0.0] * 5  # A, ×, B, separator, HOW

    def _init_fonts(self):
        font_path = MENLO_PATH if Path(MENLO_PATH).exists() else None
        self.font_lg = FTFont(font_path, 22)
        self.font_lg.strong = True
        self.font_md = FTFont(font_path, 16)
        self.font_sm = FTFont(font_path, 13)
        self.font_xs = FTFont(font_path, 11)
        self.font_title = FTFont(font_path, 20)
        self.font_title.strong = True

    # ── Text helpers ─────────────────────────────────────────────────────

    def _render(self, font, text, color):
        surf, _ = font.render(text, fgcolor=color)
        return surf

    def _text_w(self, font, text):
        return font.get_rect(text).width

    def _line_h(self, font):
        return int(font.get_sized_height()) + 2

    def _fade_color(self, color, alpha):
        """Blend color toward background based on alpha (0=bg, 1=full)."""
        return (
            int(BG[0] + (color[0] - BG[0]) * alpha),
            int(BG[1] + (color[1] - BG[1]) * alpha),
            int(BG[2] + (color[2] - BG[2]) * alpha),
        )

    def _wrap(self, text, font, max_w):
        words = text.split()
        lines, cur = [], ""
        for word in words:
            test = cur + (" " if cur else "") + word
            if self._text_w(font, test) <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines

    # ── Card operations ──────────────────────────────────────────────────

    def _pick_card(self):
        self.current_card, self.current_tradition = random.choice(self.all_cards)

    def _pick_mutate(self):
        picks = random.sample(self.mutate_pool, 3)
        self.card_a = {"card": picks[0][0], "tradition": picks[0][1]}
        self.card_b = {"card": picks[1][0], "tradition": picks[1][1]}
        self.directive = {"card": picks[2][0], "tradition": picks[2][1]}

    # ── Input ────────────────────────────────────────────────────────────

    def handle_action(self):
        if self.mode == MODE_DRAW:
            self._handle_draw_action()
        else:
            self._handle_mutate_action()

    def _handle_draw_action(self):
        if self.state == STATE_IDLE:
            # Draw new card
            self._pick_card()
            self.state = STATE_REVEALING
            self.anim_start = time.time()
            self.fade_alpha = 0.0
        elif self.state == STATE_REVEALED:
            # Flip back to face-down
            self.state = STATE_HIDING
            self.anim_start = time.time()
        elif self.state == STATE_HIDING:
            # Already hiding, ignore
            pass
        elif self.state == STATE_REVEALING:
            # Skip to revealed
            self.fade_alpha = 1.0
            self.state = STATE_REVEALED
            self.reveal_time = time.time()

    def _handle_mutate_action(self):
        if self.state == STATE_IDLE or self.state == STATE_REVEALED:
            self._pick_mutate()
            self.state = STATE_REVEALING
            self.anim_start = time.time()
            self.mutate_line_alphas = [0.0] * 5

    def toggle_mode(self):
        if self.state == STATE_REVEALING or self.state == STATE_HIDING:
            return
        self.mode = MODE_MUTATE if self.mode == MODE_DRAW else MODE_DRAW
        self.state = STATE_IDLE
        self.current_card = None
        self.card_a = None
        self.fade_alpha = 0.0

    # ── Update ───────────────────────────────────────────────────────────

    def update(self):
        now = time.time()
        elapsed = now - self.anim_start

        if self.mode == MODE_DRAW:
            if self.state == STATE_REVEALING:
                self.fade_alpha = min(elapsed / FADE_DURATION, 1.0)
                if self.fade_alpha >= 1.0:
                    self.state = STATE_REVEALED
                    self.reveal_time = now
            elif self.state == STATE_REVEALED:
                # Auto-flip back after absorb duration
                if now - self.reveal_time >= ABSORB_DURATION:
                    self.state = STATE_HIDING
                    self.anim_start = now
            elif self.state == STATE_HIDING:
                self.fade_alpha = max(1.0 - elapsed / FADE_DURATION, 0.0)
                if self.fade_alpha <= 0.0:
                    self.state = STATE_IDLE
                    self.current_card = None
        else:
            # Mutate mode: staggered reveal
            if self.state == STATE_REVEALING:
                for i in range(5):
                    line_start = i * STAGGER_DELAY
                    if elapsed > line_start:
                        progress = min((elapsed - line_start) / FADE_DURATION, 1.0)
                        self.mutate_line_alphas[i] = progress
                if all(a >= 1.0 for a in self.mutate_line_alphas):
                    self.state = STATE_REVEALED

    # ── Render ───────────────────────────────────────────────────────────

    def render(self):
        w, h = self.screen.get_size()
        self.screen.fill(BG)

        # Outer frame
        self._draw_outer_frame(w, h)

        # Mode tabs
        self._draw_mode_tabs(w)

        # Title
        self._draw_title(w)

        # Main content
        if self.mode == MODE_DRAW:
            self._render_draw(w, h)
        else:
            self._render_mutate(w, h)

        # Bottom hints
        self._draw_hints(w, h)

        pygame.display.flip()

    def _draw_outer_frame(self, w, h):
        """Draw the outer terminal box-drawing frame."""
        margin = 8
        # Top
        top_line = BOX_TL + BOX_H * ((w - 2 * margin) // CHAR_W_APPROX - 2) + BOX_TR
        top_surf = self._render(self.font_sm, top_line, BORDER)
        self.screen.blit(top_surf, (margin, margin))

        # Bottom
        bot_line = BOX_BL + BOX_H * ((w - 2 * margin) // CHAR_W_APPROX - 2) + BOX_BR
        bot_surf = self._render(self.font_sm, bot_line, BORDER)
        self.screen.blit(bot_surf, (margin, h - margin - self._line_h(self.font_sm)))

        # Sides
        lh = self._line_h(self.font_sm)
        y = margin + lh
        while y < h - margin - lh:
            left_surf = self._render(self.font_sm, BOX_V, BORDER)
            self.screen.blit(left_surf, (margin, y))
            right_surf = self._render(self.font_sm, BOX_V, BORDER)
            rw = self._text_w(self.font_sm, BOX_V)
            frame_w = self._text_w(self.font_sm, top_line)
            self.screen.blit(right_surf, (margin + frame_w - rw, y))
            y += lh

    def _draw_mode_tabs(self, w):
        """Draw clickable mode tabs at top."""
        y = 30
        if self.mode == MODE_DRAW:
            draw_label = "[▓ DRAW ▓]"
            mutate_label = "[ MUTATE ]"
            draw_color = TEXT_BRT
            mutate_color = TEXT_GHOST
        else:
            draw_label = "[ DRAW ]"
            mutate_label = "[▓ MUTATE ▓]"
            draw_color = TEXT_GHOST
            mutate_color = TEXT_BRT

        # Horizontal separator below tabs
        sep_line = BOX_T_RIGHT + BOX_H * ((w - 40) // CHAR_W_APPROX) + BOX_T_LEFT
        sep_surf = self._render(self.font_sm, sep_line, BORDER)

        draw_surf = self._render(self.font_md, draw_label, draw_color)
        mutate_surf = self._render(self.font_md, mutate_label, mutate_color)

        x_draw = 30
        x_mutate = x_draw + draw_surf.get_width() + 20

        self.screen.blit(draw_surf, (x_draw, y))
        self.screen.blit(mutate_surf, (x_mutate, y))

        # Store tab rects for click detection
        self._tab_draw_rect = pygame.Rect(x_draw, y, draw_surf.get_width(), draw_surf.get_height())
        self._tab_mutate_rect = pygame.Rect(x_mutate, y, mutate_surf.get_width(), mutate_surf.get_height())

        # Separator
        self.screen.blit(sep_surf, (12, y + self._line_h(self.font_md) + 2))

    def _draw_title(self, w):
        """Draw the CREATRIX title."""
        y = 72
        title = "░▒▓█ C R E A T R I X █▓▒░"
        title_surf = self._render(self.font_title, title, TEXT)
        self.screen.blit(title_surf, (w // 2 - title_surf.get_width() // 2, y))

        if self.mode == MODE_DRAW:
            sub = "a chaos oracle by pop chaos"
            sub_color = TEXT_DIM
        else:
            sub = "M U T A T E"
            sub_color = UV_VIOLET
        sub_surf = self._render(self.font_sm, sub, sub_color)
        self.screen.blit(sub_surf, (w // 2 - sub_surf.get_width() // 2, y + 28))

    def _draw_hints(self, w, h):
        """Draw bottom hint bar."""
        action = "draw" if self.mode == MODE_DRAW else "mutate"
        mode_name = "mutate" if self.mode == MODE_DRAW else "draw"
        hint = f"[ SPACE ] {action}  │  [ M ] {mode_name}  │  {self.deck_size}"
        hint_surf = self._render(self.font_xs, hint, TEXT_DIM)
        self.screen.blit(hint_surf, (w // 2 - hint_surf.get_width() // 2, h - 32))

    # ── DRAW MODE ────────────────────────────────────────────────────────

    def _render_draw(self, w, h):
        cx = w // 2
        card_w = min(w - 80, 500)
        card_top = 130
        card_bot = h - 60

        if self.state == STATE_IDLE:
            # Face-down card: filled with ░ characters inside a box
            self._draw_card_frame(cx, card_top, card_w, card_bot - card_top, face_up=False)
        else:
            # Card with text (fading in or out based on fade_alpha)
            self._draw_card_frame(cx, card_top, card_w, card_bot - card_top, face_up=True)
            if self.current_card:
                self._draw_card_content(cx, card_top, card_w, card_bot - card_top)

    def _draw_card_frame(self, cx, top, card_w, card_h, face_up):
        """Draw a box-drawing card frame."""
        left = cx - card_w // 2
        inner_chars = max(1, (card_w - 20) // CHAR_W_APPROX)

        border_color = TEXT if face_up else BORDER

        # Top border
        top_line = BOX_TL + BOX_H * inner_chars + BOX_TR
        top_surf = self._render(self.font_md, top_line, border_color)
        self.screen.blit(top_surf, (left, top))

        # Bottom border
        bot_line = BOX_BL + BOX_H * inner_chars + BOX_BR
        bot_surf = self._render(self.font_md, bot_line, border_color)
        self.screen.blit(bot_surf, (left, top + card_h - self._line_h(self.font_md)))

        # Side borders + fill
        lh = self._line_h(self.font_md)
        y = top + lh
        line_count = 0
        while y < top + card_h - lh:
            left_v = self._render(self.font_md, BOX_V, border_color)
            right_v = self._render(self.font_md, BOX_V, border_color)
            frame_w = self._text_w(self.font_md, top_line)
            self.screen.blit(left_v, (left, y))
            self.screen.blit(right_v, (left + frame_w - self._text_w(self.font_md, BOX_V), y))

            if not face_up:
                # Fill with ░ characters
                fill = "░" * (inner_chars - 1)
                fill_surf = self._render(self.font_md, fill, TEXT_GHOST)
                self.screen.blit(fill_surf, (left + self._text_w(self.font_md, BOX_V + " "), y))

                # Center diamond on middle line
                if line_count == (card_h // lh) // 2 - 1:
                    diamond = "◆"
                    d_surf = self._render(self.font_lg, diamond, TEXT_DIM)
                    self.screen.blit(d_surf, (cx - d_surf.get_width() // 2, y))

            y += lh
            line_count += 1

    def _draw_card_content(self, cx, top, card_w, card_h):
        """Draw card text and tradition inside the frame."""
        alpha = self.fade_alpha
        text_color = self._fade_color(TEXT_BRT, alpha)
        trad_color = self._fade_color(TEXT_DIM, alpha)
        div_color = self._fade_color(BORDER, alpha)

        max_text_w = card_w - 80
        lines = self._wrap(self.current_card, self.font_md, max_text_w)
        lh = self._line_h(self.font_md)

        # Center text vertically in card
        total_text_h = len(lines) * lh + 40  # text + divider + tradition
        start_y = top + (card_h - total_text_h) // 2

        for i, line in enumerate(lines):
            surf = self._render(self.font_md, line, text_color)
            self.screen.blit(surf, (cx - surf.get_width() // 2, start_y + i * lh))

        # Divider
        div_y = start_y + len(lines) * lh + 10
        div_text = "──────────────────"
        div_surf = self._render(self.font_sm, div_text, div_color)
        self.screen.blit(div_surf, (cx - div_surf.get_width() // 2, div_y))

        # Tradition
        if self.current_tradition:
            trad_text = f"[{self.current_tradition.upper()}]"
            trad_surf = self._render(self.font_sm, trad_text, trad_color)
            self.screen.blit(trad_surf, (cx - trad_surf.get_width() // 2, div_y + 18))

    # ── MUTATE MODE ──────────────────────────────────────────────────────

    def _render_mutate(self, w, h):
        if self.state == STATE_IDLE:
            prompt = "Press SPACE to mutate"
            p_surf = self._render(self.font_md, prompt, TEXT_GHOST)
            self.screen.blit(p_surf, (w // 2 - p_surf.get_width() // 2, h // 2))
            return
        if not self.card_a:
            return

        lm = max(40, w // 10)
        content_w = w - 2 * lm
        y = 130

        alphas = self.mutate_line_alphas

        # Card A
        if alphas[0] > 0:
            y = self._draw_mutate_card("A", self.card_a, lm, y, content_w, alphas[0])
        y += 12

        # × symbol
        if alphas[1] > 0:
            sym_color = self._fade_color(TEXT_DIM, alphas[1])
            sym_surf = self._render(self.font_md, "×", sym_color)
            self.screen.blit(sym_surf, (lm + 20, y))
        y += 22

        # Card B
        if alphas[2] > 0:
            y = self._draw_mutate_card("B", self.card_b, lm, y, content_w, alphas[2])
        y += 16

        # Separator bar
        if alphas[3] > 0:
            bar_color = self._fade_color(TEXT_DIM, alphas[3])
            bar_text = "▓" * (content_w // CHAR_W_APPROX)
            bar_surf = self._render(self.font_sm, bar_text, bar_color)
            self.screen.blit(bar_surf, (lm, y))
        y += 20

        # HOW: Directive
        if alphas[4] > 0:
            how_color = self._fade_color(UV_VIOLET, alphas[4])
            how_label = self._render(self.font_md, "HOW:", how_color)
            self.screen.blit(how_label, (lm, y))
            y += 24

            dir_lines = self._wrap(self.directive["card"], self.font_md, content_w - 20)
            lh = self._line_h(self.font_md)
            for i, line in enumerate(dir_lines):
                surf = self._render(self.font_md, line, how_color)
                self.screen.blit(surf, (lm + 10, y + i * lh))
            y += len(dir_lines) * lh + 6

            trad = f"[{self.directive['tradition'].upper()}]"
            trad_surf = self._render(self.font_xs, trad, self._fade_color(TEXT_GHOST, alphas[4]))
            self.screen.blit(trad_surf, (lm + 10, y))

    def _draw_mutate_card(self, label, card_data, x, y, max_w, alpha):
        label_color = self._fade_color(RED_CORE, alpha)
        text_color = self._fade_color(TEXT, alpha)
        trad_color = self._fade_color(TEXT_GHOST, alpha)

        # Label: A ═══
        lbl = f"{label} ═══"
        lbl_surf = self._render(self.font_md, lbl, label_color)
        self.screen.blit(lbl_surf, (x, y))
        y += self._line_h(self.font_md) + 2

        # Card text (quoted)
        card_text = f'"{card_data["card"]}"'
        lines = self._wrap(card_text, self.font_md, max_w - 30)
        lh = self._line_h(self.font_md)
        for i, line in enumerate(lines):
            surf = self._render(self.font_md, line, text_color)
            self.screen.blit(surf, (x + 24, y + i * lh))
        y += len(lines) * lh + 2

        # Tradition
        trad = f"[{card_data['tradition'].upper()}]"
        trad_surf = self._render(self.font_xs, trad, trad_color)
        self.screen.blit(trad_surf, (x + 24, y))
        y += 16
        return y

    # ── Main loop ────────────────────────────────────────────────────────

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
                        self.handle_action()
                    elif event.key == pygame.K_m:
                        self.toggle_mode()
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1:
                        pos = event.pos
                        # Check tab clicks
                        if hasattr(self, '_tab_draw_rect') and self._tab_draw_rect.collidepoint(pos):
                            if self.mode != MODE_DRAW:
                                self.toggle_mode()
                        elif hasattr(self, '_tab_mutate_rect') and self._tab_mutate_rect.collidepoint(pos):
                            if self.mode != MODE_MUTATE:
                                self.toggle_mode()
                        else:
                            self.handle_action()

            self.update()
            self.render()
            self.clock.tick(FPS)

        pygame.quit()


if __name__ == "__main__":
    app = App()
    app.run()
