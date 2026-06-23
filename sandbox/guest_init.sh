#!/bin/sh
# PID 1 inside the Firecracker microVM (booted with init=/init).
# Bring up just enough to run the payload, then power the VM off.
export PATH=/usr/local/bin:/usr/bin:/bin:/sbin

mount -t proc proc /proc 2>/dev/null
mount -t sysfs sysfs /sys 2>/dev/null
mount -t devtmpfs dev /dev 2>/dev/null
mount -t tmpfs tmpfs /tmp 2>/dev/null

mkdir -p /job
# Second drive (vdb) is the read-only per-run job disk.
mount -t ext4 -o ro /dev/vdb /job 2>/dev/null

/usr/local/bin/python3 /runner.py

sync
# Reboot the microVM. With reboot=k the kernel resets via the i8042 controller,
# which Firecracker traps and exits cleanly (a *poweroff* would only halt the
# vCPU and leave Firecracker idling). If all else fails, init exiting triggers
# the kernel's panic=1 -> reboot, which also exits Firecracker.
echo 1 > /proc/sys/kernel/sysrq 2>/dev/null
echo b > /proc/sysrq-trigger 2>/dev/null
reboot -f 2>/dev/null
