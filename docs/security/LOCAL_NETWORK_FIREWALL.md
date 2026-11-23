# Local network firewall helper

The explicit Repair connection action now narrows existing known application rules and new rules to Windows LocalSubnet, while keeping both Private and Public profiles for Windows hotspot support. Manual fallback instructions also specify the scope. It never changes router settings and this PR does not run on the owner's machine.

This does not encrypt legacy HTTP/PIN traffic, remove router port forwarding, or inspect unrelated firewall rules created under different names. Devices on the same local subnet still need application authentication. LocalSubnet can exclude a routed VLAN or VPN client; that requires a deliberately reviewed network-specific rule, not automatic global access.

Tests mock netsh argument construction and failures. Actual Windows firewall/hotspot connectivity and a post-repair RemoteIP read-back must be checked on the target computer before claiming the machine is restricted. Existing diagnostics report port/profile coverage, not an audit of all other firewall rules.
