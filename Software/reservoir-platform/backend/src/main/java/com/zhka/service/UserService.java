package com.zhka.service;

import com.zhka.entity.User;
import com.zhka.mapper.UserMapper;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 用户管理用例（管理端后台，管理端提交的是明文口令，沿用原实现）。
 *
 * <p>与 {@link AuthService} 的分工：本类负责账号的增删改查，登录鉴权在 AuthService。
 */
@Service
public class UserService {

    private final UserMapper userMapper;

    public UserService(UserMapper userMapper) {
        this.userMapper = userMapper;
    }

    public List<User> findAll() {
        return userMapper.findAll();
    }

    public User findById(Integer id) { return userMapper.findById(id); }

    public boolean exists(String username) {
        return userMapper.findByUsername(username) != null;
    }

    /**
     * 新增用户。
     *
     * @return 用户名已存在时返回 false
     */
    public boolean create(String username, String password, Integer level) {
        if (exists(username)) {
            return false;
        }
        User user = new User();
        user.setUsername(username);
        user.setPassword(password);
        user.setLevel(level);
        userMapper.insert(user);
        return true;
    }

    /**
     * 更新用户。
     *
     * @return 用户不存在时返回 false
     */
    public boolean update(Integer id, String username, String password, Integer level) {
        User user = userMapper.findById(id);
        if (user == null) {
            return false;
        }
        User sameName = userMapper.findByUsername(username);
        if (sameName != null && !id.equals(sameName.getId())) {
            return false;
        }
        user.setUsername(username);
        if (password != null && !password.isBlank()) {
            user.setPassword(password);
        }
        user.setLevel(level);
        userMapper.update(user);
        return true;
    }

    /** 删除用户；不存在时同样视为成功（与原接口一致） */
    public void delete(Integer id) {
        userMapper.delete(id);
    }

    public String changePassword(String username, String oldPassword, String newPassword) {
        User user = userMapper.findByUsername(username);
        if (user == null) return "账号不存在";
        if (oldPassword == null || !oldPassword.equals(user.getPassword())) return "原密码不正确";
        if (newPassword == null || newPassword.length() < 6) return "新密码至少需要 6 位";
        user.setPassword(newPassword);
        userMapper.update(user);
        return null;
    }
}
