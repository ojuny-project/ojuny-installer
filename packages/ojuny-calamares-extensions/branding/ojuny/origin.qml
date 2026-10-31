import io.calamares.core

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

Rectangle {
    width: parent.width
    height: parent.height
    color: "#2d353b"

    ColumnLayout {
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: 24
        spacing: 8

        Text {
            Layout.fillWidth: true
            color: "#d3c6aa"
            wrapMode: Text.WordWrap
            text: qsTr("The installed configuration is initialized as a git repository with one commit. Add an origin to connect it to your own remote now, or leave the URL empty to keep it local. This page is ignored when a prepared repository is used; that clone keeps its own remote.")
        }

        Label {
            text: qsTr("Origin URL")
            color: "#d3c6aa"
        }

        TextField {
            id: originUrlField
            Layout.fillWidth: true
            color: "#d3c6aa"
            placeholderTextColor: "#7a8478"
            placeholderText: "https://github.com/you/ojuny-template"
            background: Rectangle {
                color: "#343f44"
                border.color: "#475258"
                radius: 3
            }
            onTextChanged: Global.insert("ojuny_origin_url", text)
        }

        Label {
            text: qsTr("Git token")
            color: "#d3c6aa"
        }

        TextField {
            id: originTokenField
            Layout.fillWidth: true
            color: "#d3c6aa"
            placeholderTextColor: "#7a8478"
            echoMode: TextInput.Password
            placeholderText: qsTr("Optional, HTTPS only")
            background: Rectangle {
                color: "#343f44"
                border.color: "#475258"
                radius: 3
            }
            onTextChanged: Global.insert("ojuny_origin_token", text)
        }

        Text {
            Layout.fillWidth: true
            color: "#d3c6aa"
            wrapMode: Text.WordWrap
            text: qsTr("Credential helper: for an HTTPS URL with a token, Ojuny writes ~/.git-credentials with mode 0600 and points the repository credential helper at that file. An SSH URL uses your SSH key and gets no helper. The token is not stored anywhere else.")
        }

        Text {
            Layout.fillWidth: true
            color: "#d3c6aa"
            wrapMode: Text.WordWrap
            text: qsTr("Commit author: the initial commit is authored as Ojuny Installer <installer@ojuny.local>. You can change it later with git config.")
        }

        Text {
            Layout.fillWidth: true
            color: "#d3c6aa"
            wrapMode: Text.WordWrap
            text: qsTr("No origin: leave the URL empty to skip the remote. The repository stays local, and you can add an origin later and use the settings GUI sync button.")
        }
    }

    Component.onCompleted: {
        var savedUrl = Global.value("ojuny_origin_url") || "";
        var savedToken = Global.value("ojuny_origin_token") || "";

        if (!Global.contains("ojuny_origin_url"))
            Global.insert("ojuny_origin_url", savedUrl);
        if (!Global.contains("ojuny_origin_token"))
            Global.insert("ojuny_origin_token", savedToken);

        originUrlField.text = savedUrl;
        originTokenField.text = savedToken;
    }
}
