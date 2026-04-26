// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract StorageRegistry {
    struct FileRecord {
        bytes32 rootHash;
        address uploader;
        uint256 timestamp;
        string metadata;
    }

    mapping(uint256 => FileRecord) public files;
    uint256 public fileCount;

    event FileRegistered(uint256 indexed id, bytes32 rootHash, address uploader);

    function registerFile(bytes32 rootHash, string calldata metadata) external returns (uint256) {
        uint256 id = fileCount++;
        files[id] = FileRecord({
            rootHash: rootHash,
            uploader: msg.sender,
            timestamp: block.timestamp,
            metadata: metadata
        });
        emit FileRegistered(id, rootHash, msg.sender);
        return id;
    }

    function getFile(uint256 id) external view returns (FileRecord memory) {
        return files[id];
    }

    function verifyUploader(uint256 id, address uploader) external view returns (bool) {
        return files[id].uploader == uploader;
    }
}
