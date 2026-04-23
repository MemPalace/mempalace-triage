import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export type BadgeTone =
  | 'green'
  | 'yellow'
  | 'red'
  | 'blue'
  | 'purple'
  | 'orange'
  | 'cyan'
  | 'neutral';

@Component({
  selector: 'app-badge',
  templateUrl: './badge.html',
  styleUrl: './badge.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    '[attr.data-tone]': 'tone()',
  },
})
export class Badge {
  readonly tone = input<BadgeTone>('neutral');
  readonly label = input.required<string>();

  protected readonly toneClasses = computed(() => `tone-${this.tone()}`);
}
