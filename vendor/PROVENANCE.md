# Vendor SDK provenance and distribution boundary

These are **manufacturer-supplied binaries**, not built from this repository's
C++ source. Their presence does not establish an open-source license or permission
to redistribute them publicly. The generated wheels are local/private artifacts;
no PyPI/GitHub release publication is configured. Obtain the manufacturer's
redistribution permission before public distribution, and review all bundled
third-party notices. This file is not a legal grant.

| Platform | Input | SHA-256 before wheel repair |
|---|---|---|
| Linux x86_64 | `vendor/linux/libiimtcl.so` | `09db616a60d1b978ea1c5fac6a5e46b078bbae1203b347ebca536b144511f84b` |
| Windows x64 MSVC | `vendor/windows/iimtcl.dll` | `9338fd37c196b6c4d68a1a639235c7e337098f0e93407ef0369a730fa15cfadf` |

Linux input is copied from the currently working ROS project's
`iimt_ros2_driver/lib/lib64/libiimtcl.so`. It is deliberately **not** silently
replaced by the newer archive's Linux library (archive SHA-256
`424849e9f7287f1747c015d547b3c501c9845c9e941976edac1c8b627c2ebc62`).
Windows input comes from manufacturer archive
`IIMT-SDK/C++/windows/x64/MSVC 2022/lib/iimtcl.dll`; it has not been executed on a
native Windows host during initial development. Linux validation is not transferable
to that DLL.

The controller dynamically loads C exports. SDK joint struct: six doubles;
ServoJ parameters use 1-byte packing (68 bytes). Windows SDK handles are 64-bit;
MSVC runtime dependencies must resolve without a developer's vcpkg PATH.
`delvewheel --analyze-existing` is required because a runtime-loaded SDK does not
appear in the extension module's static import table. Repair may modify import
names/RPATH and thus binary hashes; these hashes identify the original inputs,
not necessarily repaired wheel contents.

Local Linux protocol evidence: `API_Stop` sends `stop` and polls `programState`;
`API_ClearUnfinishedTrajectory` sends `unlock protective stop` in this SDK build.
The simulator reproduces those replies, but does not prove real hardware safety
or undocumented equivalence between Linux and Windows SDK builds.

Asset models/meshes were copied from the user's existing manufacturer ROS package.
Their redistribution rights likewise require checking before public publication.
