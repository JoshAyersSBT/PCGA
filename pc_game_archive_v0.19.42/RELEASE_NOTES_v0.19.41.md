# PC Game Archive v0.19.41

This release adds an opt-in NetBird peer container to the PCGA Docker stack. The peer uses host networking so its overlay interface is available to the appliance's portal and streaming services. Its identity is stored persistently under `/var/lib/pc-game-archive/netbird`.

The Control Center's existing Remote Networking actions install, connect, check, and disconnect the container. Connect accepts a server setup key through the existing protected control API. PCGA writes the key to a root-only temporary file, mounts it read-only into the container, invokes `netbird up --setup-key-file`, and removes the host file after successful enrollment or a failed attempt. The key is not included in Compose environment values or PCGA configuration.

The NetBird service uses the `netbird` Compose profile and is not started by ordinary stack reconciliation. A native NetBird system service blocks the upgrade so the host does not run two peers. Disconnect stops the container and preserves its peer identity for a later reconnect.

Upgrade from v0.19.40 with the standard `upgrade.sh` entrypoint. The upgrade backs up changed files and validates the existing Wolf game catalog before it reports success. It does not enroll the appliance automatically. After upgrading, open Control Center → Remote Networking, install NetBird, and connect using a setup key created in the NetBird management console.

The client must independently join the same NetBird network and its access policy must allow the portal and Moonlight traffic. The current thin-client bootstrap does not issue client setup keys; use the client's supported enrollment flow.

The container image is pinned to NetBird 0.81.3. NetBird's documented Docker model uses host networking, TUN, persistent state, and the network capabilities configured by this release. Registration is considered ready only after management reports connected and `netbird status --check startup` succeeds.
