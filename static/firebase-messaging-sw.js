importScripts(
    "https://www.gstatic.com/firebasejs/12.1.0/firebase-app-compat.js"
);

importScripts(
    "https://www.gstatic.com/firebasejs/12.1.0/firebase-messaging-compat.js"
);


const firebaseConfig = {

    apiKey:
        "AIzaSyCEDu7nwRBQ0G_mdX09JoJj4AW4d5pAr5U",

    authDomain:
        "projectsanjaysie.firebaseapp.com",

    projectId:
        "projectsanjaysie",

    storageBucket:
        "projectsanjaysie.firebasestorage.app",

    messagingSenderId:
        "8747423858",

    appId:
        "1:8747423858:web:49846d0d440b069a014aeb"

};


firebase.initializeApp(firebaseConfig);


const messaging =
    firebase.messaging();


messaging.onBackgroundMessage(
    function(payload) {

        console.log(
            "Background Firebase message:",
            payload
        );


        const notificationTitle =
            payload.notification?.title
            ||
            "🚦 Smart Traffic Alert";


        const notificationOptions = {

            body:
                payload.notification?.body
                ||
                "Traffic alert received.",

            icon: "/static/icon.png",

            badge: "/static/icon.png"

        };


        self.registration.showNotification(

            notificationTitle,

            notificationOptions

        );

    }
);