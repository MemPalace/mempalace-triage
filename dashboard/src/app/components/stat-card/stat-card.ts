import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export type StatTone =
  | 'blue'
  | 'green'
  | 'yellow'
  | 'red'
  | 'orange'
  | 'purple'
  | 'cyan';

@Component({
  selector: 'app-stat-card',
  templateUrl: './stat-card.html',
  styleUrl: './stat-card.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    '[attr.data-tone]': 'tone()',
    '[style.animation-delay]': 'animationDelay()',
  },
})
export class StatCard {
  readonly value = input<string | number | null>(null);
  readonly label = input.required<string>();
  readonly subtitle = input<string | null>(null);
  readonly tone = input<StatTone>('blue');
  readonly index = input<number>(0);

  protected readonly animationDelay = computed(() => `${Math.min(this.index(), 10) * 40}ms`);
}
