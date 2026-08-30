// ==========================================
// SMART TRAFFIC PWA
// ==========================================

if ("serviceWorker" in navigator) {

    window.addEventListener(
        "load",
        async function () {

            try {

                const registration =
                    await navigator.serviceWorker.register(
                        "/firebase-messaging-sw.js"
                    );

                console.log(
                    "✅ Smart Traffic service worker registered:",
                    registration.scope
                );

            }

            catch (error) {

                console.error(
                    "❌ Service worker registration failed:",
                    error
                );

            }

        }
    );

}