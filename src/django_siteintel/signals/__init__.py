# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.dispatch import Signal

# Sent once per finished audit run, and immediately when request_audit reuses a valid audit.
# Arguments: audit (Audit), succeeded_sources (list[str]).
report_ready = Signal()
