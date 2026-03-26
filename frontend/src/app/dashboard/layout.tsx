import { NavSidebar } from "@/components/dashboard/nav-sidebar";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen">
      <NavSidebar />
      <main className="flex-1 overflow-auto">
        <div className="container mx-auto max-w-7xl p-6 pt-16 lg:pt-6">
          {children}
        </div>
      </main>
    </div>
  );
}
