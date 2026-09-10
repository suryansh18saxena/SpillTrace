"""Background job execution.

The database holds job state; Redis is only the transport (AD-3).  A worker that dies
mid-job loses nothing: the row still says RUNNING with its last heartbeat, and the
reaper requeues it.
"""
