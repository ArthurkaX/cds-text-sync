// The folder dialog Explorer shows (IFileOpenDialog with FOS_PICKFOLDERS):
// an address bar, the quick-access list and a typed path, where WinForms'
// FolderBrowserDialog on .NET Framework 4.8 is the old tree of the whole
// shell.  The COM interfaces are declared here in vtable order; a slot this
// file never calls is declared without parameters, since only its place in
// the table matters.
using System;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace Cts.Agent
{
    internal static class FolderPicker
    {
        const uint FOS_PICKFOLDERS = 0x20;
        const uint FOS_FORCEFILESYSTEM = 0x40;
        const uint FOS_PATHMUSTEXIST = 0x800;
        const uint SIGDN_FILESYSPATH = 0x80058000;
        const int ERROR_CANCELLED = unchecked((int)0x800704C7);

        // The folder chosen, or null when the user cancelled.  The dialog
        // opens in *initial*, or the nearest folder above it that exists.
        public static string Pick(IWin32Window owner, string title, string initial)
        {
            var dialog = (IFileOpenDialog)new FileOpenDialog();
            try
            {
                dialog.SetOptions(FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST);
                if (!string.IsNullOrEmpty(title)) dialog.SetTitle(title);
                while (!string.IsNullOrEmpty(initial) && !System.IO.Directory.Exists(initial))
                    initial = System.IO.Path.GetDirectoryName(initial);
                if (!string.IsNullOrEmpty(initial))
                {
                    IShellItem folder;
                    if (SHCreateItemFromParsingName(initial, IntPtr.Zero, typeof(IShellItem).GUID, out folder) == 0)
                    {
                        dialog.SetFolder(folder);
                        Marshal.ReleaseComObject(folder);
                    }
                }
                var shown = dialog.Show(owner == null ? IntPtr.Zero : owner.Handle);
                if (shown == ERROR_CANCELLED) return null;
                Marshal.ThrowExceptionForHR(shown);
                IShellItem result;
                dialog.GetResult(out result);
                try
                {
                    string path;
                    result.GetDisplayName(SIGDN_FILESYSPATH, out path);
                    return path;
                }
                finally
                {
                    Marshal.ReleaseComObject(result);
                }
            }
            finally
            {
                Marshal.ReleaseComObject(dialog);
            }
        }

        [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
        static extern int SHCreateItemFromParsingName(string path, IntPtr bindContext,
            [MarshalAs(UnmanagedType.LPStruct)] Guid riid, out IShellItem item);

        [ComImport, Guid("DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7")]
        class FileOpenDialog
        {
        }

        [ComImport, Guid("d57c7288-d4ad-4768-be02-9d969532d960"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        interface IFileOpenDialog
        {
            // IModalWindow
            [PreserveSig] int Show(IntPtr owner);
            // IFileDialog
            void SetFileTypes();
            void SetFileTypeIndex();
            void GetFileTypeIndex();
            void Advise();
            void Unadvise();
            void SetOptions(uint options);
            void GetOptions();
            void SetDefaultFolder();
            void SetFolder(IShellItem folder);
            void GetFolder();
            void GetCurrentSelection();
            void SetFileName();
            void GetFileName();
            void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string title);
            void SetOkButtonLabel();
            void SetFileNameLabel();
            void GetResult(out IShellItem item);
        }

        [ComImport, Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        interface IShellItem
        {
            void BindToHandler();
            void GetParent();
            void GetDisplayName(uint form, [MarshalAs(UnmanagedType.LPWStr)] out string name);
        }
    }
}
