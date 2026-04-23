import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { DatePipe } from '@angular/common';
import type { ConnectionState } from '../../models/triage';

@Component({
  selector: 'app-dashboard-header',
  imports: [DatePipe],
  templateUrl: './dashboard-header.html',
  styleUrl: './dashboard-header.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DashboardHeader {
  readonly connectionState = input.required<ConnectionState>();
  readonly lastUpdated = input<number | null>(null);

  protected readonly dotClass = computed(() => `status-${this.connectionState()}`);

  protected readonly connectionLabel = computed(() => {
    switch (this.connectionState()) {
      case 'open':
        return 'Streaming live';
      case 'connecting':
        return 'Connecting';
      case 'closed':
        return 'Reconnecting';
    }
  });
}
